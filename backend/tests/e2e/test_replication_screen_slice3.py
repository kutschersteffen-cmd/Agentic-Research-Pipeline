"""Strategy Replication screen (spec strategy-replication-fixes, slice 3): uploads, another spec, drawdown.

The API is stubbed by Playwright routing, so the rows run without a model key.
"""

import json
import re

import pytest

from arp.schemas.strategy_replication import (
    BacktestResult,
    LegPerformance,
    PortfolioPeriodReturn,
    RebalanceFrequency,
    ReplicationComparisonReport,
    ReportedPerformance,
    SignalType,
    StrategySpec,
    WeightingScheme,
)
from tests.e2e.test_ui_polish_1 import URL, _open, page  # noqa: F401  (page is a fixture)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

UPLOAD = {"ref": "prices.csv", "tickers": ["T0", "T1", "T2"], "rows": 24, "first_date": "1965-01-01", "last_date": "1966-12-01"}


def _spec(name, **kw):
    kw.setdefault("signal_type", SignalType.MOMENTUM)
    return StrategySpec(
        paper_citation="T (2020)", paper_title="T", strategy_name=name, universe_description="u",
        formation_period_months=6, holding_period_months=6, rebalance_frequency=RebalanceFrequency.MONTHLY, num_portfolios=4,
        long_leg_portfolio=1, short_leg_portfolio=4, weighting=WeightingScheme.EQUAL, sample_period_start="1965-01-01",
        sample_period_end="1969-12-31", **kw,
    ).model_dump(mode="json")


def _detail(returns):
    spec = StrategySpec.model_validate(_spec("Alpha"))
    periods = [
        PortfolioPeriodReturn(period_end=f"1965-0{i + 1}-01", long_return_pct=0, short_return_pct=0, long_short_return_pct=r, num_long=1, num_short=1)
        for i, r in enumerate(returns)
    ]
    result = BacktestResult(
        spec_id=spec.spec_id, period_label="in_sample", period_start="1965-01-01", period_end="1965-12-01", data_source="csv",
        universe_size=3, periods=periods, long_short=LegPerformance(annualized_return_pct=1.0),
    )
    report = ReplicationComparisonReport(
        spec_id=spec.spec_id, in_sample=result, reported_performance=ReportedPerformance(), verdict="replicated",
    )
    return {"run_id": "run_r", "spec": spec.model_dump(mode="json"), "in_sample": result.model_dump(mode="json"),
            "comparison": report.model_dump(mode="json")}


class Stub:
    """Answers every /api/replication request; `upload` is a status and body, or "abort", or "hold"."""

    def __init__(self, pg, characteristic=None, returns=(10, -50, 20)):
        self.upload = (200, UPLOAD)
        self.held = []
        self.requests = []
        self.specs = {k: _spec(n, **({"signal_type": "value", "characteristic_name": characteristic} if characteristic else {}))
                      for k, n in (("run_a", "Alpha"), ("run_b", "Beta"))}
        self.detail = _detail(returns)
        pg.route(re.compile(r".*/api/replication/.*"), self.handle)

    def _json(self, route, body, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

    def handle(self, route):
        req = route.request
        path = req.url.split("/api/replication", 1)[1]
        self.requests.append((req.method, path, req.post_data))
        if "/datasets/" in path:
            if self.upload == "hold":
                self.held.append(route)
            elif self.upload == "abort":
                route.abort()
            else:
                status, body = self.upload
                self._json(route, body if status == 200 else {"detail": body}, status)
        elif path.endswith("/backtest"):
            self._json(route, {"run_id": "run_r", "verdict": "replicated"})
        elif path.startswith("/runs/"):
            self._json(route, self.detail)
        elif re.fullmatch(r"/specs/run_[ab]", path):
            key = path.rsplit("/", 1)[1]
            self._json(route, {"spec_run_id": key, "spec": self.specs[key], "approved": True, "history": []})
        else:
            route.continue_()


def _load(pg, key):
    pg.get_by_placeholder("spec draft run ID").fill(key)
    pg.get_by_role("button", name="Resume").click()
    pg.get_by_role("heading", name="3. Run the backtest & review results").wait_for()


def _pick(pg, name, label=None):
    box = pg.get_by_label(label) if label else pg.locator('input[type="file"]').first
    box.set_input_files({"name": name, "mimeType": "text/csv", "buffer": b"date,T0\n"})


def _open_screen(pg):
    _open(pg, "/#/strategyReplication")


def _status(pg, which="prices"):
    return pg.locator(f'[data-upload-status="{which}"]')


def test_status_line_summary_and_tickers_fill(page):  # noqa: F811  AC-42, AC-44, AC-45, AC-46
    stub = Stub(page)
    stub.upload = "hold"
    _open_screen(page)
    _load(page, "run_a")
    _pick(page, "f.csv")
    page.wait_for_function("document.querySelector('[data-upload-status=prices]').textContent === 'Uploading f.csv…'")
    assert page.get_by_role("button", name="Run backtest").is_disabled()
    assert page.locator('input[type="file"]').first.is_disabled()
    stub.held[0].fulfill(status=200, content_type="application/json", body=json.dumps(UPLOAD))
    page.wait_for_function("document.querySelector('[data-upload-status=prices]').textContent.startsWith('Uploaded')")
    assert _status(page).inner_text() == "Uploaded f.csv: 3 tickers, 24 rows, 1965-01-01 to 1966-12-01."
    assert page.get_by_label("Tickers (comma or newline separated)").input_value() == "T0, T1, T2"
    assert page.get_by_role("button", name="Run backtest").is_enabled()
    assert page.locator('input[type="file"]').first.is_enabled()
    assert page.locator('input[type="file"]').first.input_value() == ""


def test_a_filled_tickers_box_is_left_alone(page):  # noqa: F811  AC-47
    Stub(page)
    _open_screen(page)
    _load(page, "run_a")
    page.get_by_label("Tickers (comma or newline separated)").fill("T1")
    _pick(page, "f.csv")
    _status(page).filter(has_text="Uploaded f.csv").wait_for()
    assert page.get_by_label("Tickers (comma or newline separated)").input_value() == "T1"


def test_a_refused_upload_shows_the_error_and_drops_the_file(page):  # noqa: F811  AC-48, AC-65, AC-66, AC-67, AC-69, AC-50, AC-79
    stub = Stub(page)
    _open_screen(page)
    _load(page, "run_a")
    page.get_by_label("Tickers (comma or newline separated)").fill("T0")
    _pick(page, "f.csv")
    _status(page).filter(has_text="Uploaded f.csv").wait_for()
    stub.upload = (413, "File is larger than the 100 MB upload limit.")
    _pick(page, "g.csv")
    alert = page.locator('[role="alert"][data-upload-error="prices"]')
    assert alert.inner_text() == "413: File is larger than the 100 MB upload limit."
    assert _status(page).inner_text() == ""
    assert page.get_by_role("button", name="Run backtest").is_disabled()
    assert page.locator('input[type="file"]').first.is_enabled()
    assert page.locator('input[type="file"]').first.input_value() == ""
    stub.upload = (200, UPLOAD)
    _pick(page, "g.csv")
    _status(page).filter(has_text="Uploaded g.csv").wait_for()
    assert page.locator('[data-upload-error="prices"]').count() == 0


def test_no_answer_reads_as_such_and_the_input_comes_back(page):  # noqa: F811  AC-49, AC-68
    stub = Stub(page)
    stub.upload = "abort"
    _open_screen(page)
    _load(page, "run_a")
    _pick(page, "f.csv")
    alert = page.locator('[data-upload-error="prices"]')
    assert alert.inner_text() == "Upload failed: no answer from the server."
    assert page.locator('input[type="file"]').first.is_enabled()


def test_a_failed_characteristics_upload_keeps_the_backtest_enabled(page):  # noqa: F811  AC-51, AC-73
    stub = Stub(page, characteristic="book to market")
    _open_screen(page)
    _load(page, "run_a")
    page.get_by_label("Tickers (comma or newline separated)").fill("T0")
    _pick(page, "f.csv")
    _status(page).filter(has_text="Uploaded f.csv").wait_for()
    stub.upload = (400, "Not a usable CSV: no data rows.")
    _pick(page, "c.csv", "book to market characteristics CSV")
    alert = page.locator('[role="alert"][data-upload-error="characteristics"]')
    assert alert.inner_text() == "400: Not a usable CSV: no data rows."
    assert page.get_by_role("button", name="Run backtest").is_enabled()


def test_another_spec_starts_clean_and_the_same_one_keeps_its_upload(page):  # noqa: F811  AC-52 to AC-54, AC-70 to AC-72, AC-74, AC-75, AC-77
    Stub(page)
    _open_screen(page)
    _load(page, "run_a")
    page.get_by_label("Tickers (comma or newline separated)").fill("T0")
    _pick(page, "f.csv")
    _status(page).filter(has_text="Uploaded f.csv").wait_for()
    page.get_by_role("button", name="Run backtest").click()
    page.get_by_text("Verdict", exact=True).wait_for()
    page.get_by_label("Give an instruction in natural language").fill("abc")
    editor = page.locator("textarea.review-json-edit")
    editor.fill("{")
    page.get_by_role("button", name="Save direct edit").click()
    review = page.locator("section", has=page.get_by_role("heading", name="2. Review the spec sheet"))
    review.get_by_role("alert").wait_for()

    _load(page, "run_a")  # the same spec again: editor reloaded, upload kept
    page.wait_for_function("document.querySelector('textarea.review-json-edit').value !== '{'")
    assert json.loads(editor.input_value())["strategy_name"] == "Alpha"
    assert _status(page).inner_text().startswith("Uploaded f.csv")

    page.get_by_placeholder("spec draft run ID").fill("run_b")
    page.get_by_role("button", name="Resume").click()
    page.wait_for_function("JSON.parse(document.querySelector('textarea.review-json-edit').value).strategy_name === 'Beta'")
    assert page.get_by_label("Give an instruction in natural language").input_value() == ""
    assert review.get_by_role("alert").count() == 0
    assert _status(page).inner_text() == ""
    assert page.get_by_label("Tickers (comma or newline separated)").input_value() == ""
    assert page.get_by_role("button", name="Run backtest").is_disabled()
    assert page.get_by_text("Verdict", exact=True).count() == 0


@pytest.mark.parametrize("returns, latest", [((-100, 10), "0.0%"), ((10, -50, 20), "40.0%")])
def test_drawdown_depth_is_never_nan(page, returns, latest):  # noqa: F811  AC-56, AC-57, AC-58
    Stub(page, returns=returns)
    _open_screen(page)
    _load(page, "run_a")
    page.get_by_label("Tickers (comma or newline separated)").fill("T0")
    _pick(page, "f.csv")
    _status(page).filter(has_text="Uploaded f.csv").wait_for()
    page.get_by_role("button", name="Run backtest").click()
    chart = page.get_by_role("heading", name="Drawdown depth (long-short, 0 = at a new high)").locator("xpath=following-sibling::*[1]")
    svg = chart.locator("svg").first
    svg.wait_for()
    assert (svg.get_attribute("aria-label") or "").endswith(f"Latest: Long-short drawdown depth {latest}")
    assert "NaN" not in page.locator("section", has=page.get_by_role("heading", name="3. Run the backtest & review results")).inner_html()
