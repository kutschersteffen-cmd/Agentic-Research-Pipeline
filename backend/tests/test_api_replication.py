import csv
import io
import random

import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.auth import current_user
from arp.api.routers import replication
from arp.api.routers.replication import (
    ApproveSpecRequest,
    BacktestRequest,
    CreateSpecRequest,
    ReviseSpecRequest,
    approve_spec_draft,
    create_spec_draft,
    get_replication_run,
    get_spec_draft,
    revise_spec_draft,
    run_backtest_from_spec,
    trigger_regime_report,
    trigger_sanity_check,
    update_spec_draft,
    upload_characteristics_dataset,
    upload_price_dataset,
)
from arp.config import Settings
from arp.replication.spec_extractor_agent import StrategySpecDraft
from arp.replication.spec_revision import _current_revision_draft
from arp.replication.spec_verifier_agent import SpecVerifierOutput
from arp.schemas.strategy_replication import RebalanceFrequency, ReportedPerformance, SignalType, StrategySpec, WeightingScheme
from arp.storage.run_store import RunStore
from tests.conftest import PRINCIPAL
from tests.postgres_helpers import pg_dsn

pytestmark = pytest.mark.usefixtures("pg")  # pg_dsn() helpers below

_PAPER_TEXT = (
    "We form decile portfolios based on the prior 6-month formation period return and hold them "
    "for 6 months. NYSE ordinary common shares, sample period 1965 to 1989."
)


def _draft() -> StrategySpecDraft:
    return StrategySpecDraft(
        paper_title="Test momentum paper",
        strategy_name="6-6 momentum",
        signal_type=SignalType.MOMENTUM,
        universe_description="NYSE ordinary common shares",
        formation_period_months=6,
        holding_period_months=6,
        rebalance_frequency=RebalanceFrequency.MONTHLY,
        num_portfolios=4,
        long_leg_portfolio=1,
        short_leg_portfolio=4,
        weighting=WeightingScheme.EQUAL,
        sample_period_start="1965-01-01",
        sample_period_end="1969-12-31",
        reported_performance=ReportedPerformance(),
        citations=[],
        confidence=0.9,
    )


async def _drafted_spec_run_id(run_store, fake_llm) -> str:
    llm = fake_llm({"StrategySpecDraft": [_draft()], "SpecVerifierOutput": [SpecVerifierOutput(agrees=True, confidence=0.85, notes="ok")]})
    result = await create_spec_draft(
        CreateSpecRequest(paper_citation="Test (2020)", paper_text=_PAPER_TEXT),
        run_store=run_store, llm=llm, verifier_llm=llm, settings=_settings(),
    )
    return result["spec_run_id"]


def _settings():
    from arp.config import get_settings

    return get_settings()


def _run_store(tmp_path) -> RunStore:
    return RunStore(pg_dsn(), tmp_path / "runs")


async def test_create_spec_draft_is_unapproved(tmp_path, fake_llm):
    run_store = _run_store(tmp_path)
    spec_run_id = await _drafted_spec_run_id(run_store, fake_llm)

    state = get_spec_draft(spec_run_id, run_store=run_store)
    assert state["approved"] is False
    assert state["spec"]["strategy_name"] == "6-6 momentum"
    assert state["history"] == []


def test_get_spec_draft_404_for_unknown_id(tmp_path):
    run_store = _run_store(tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        get_spec_draft("nope", run_store=run_store)
    assert exc_info.value.status_code == 404


async def test_approve_then_edit_unapproves(tmp_path, fake_llm):
    run_store = _run_store(tmp_path)
    spec_run_id = await _drafted_spec_run_id(run_store, fake_llm)

    approved = approve_spec_draft(spec_run_id, ApproveSpecRequest(reviewer="alice"), run_store=run_store, principal=PRINCIPAL)
    assert approved["approved"] is True

    current_state = get_spec_draft(spec_run_id, run_store=run_store)
    edited_spec = StrategySpec.model_validate(current_state["spec"])
    edited_spec.holding_period_months = 12
    result = update_spec_draft(spec_run_id, edited_spec, run_store=run_store, principal=PRINCIPAL)

    assert result["approved"] is False  # editing after approval un-approves
    assert result["spec"]["holding_period_months"] == 12


async def test_revise_via_instruction_records_history_entry(tmp_path, fake_llm):
    run_store = _run_store(tmp_path)
    spec_run_id = await _drafted_spec_run_id(run_store, fake_llm)
    current = StrategySpec.model_validate(get_spec_draft(spec_run_id, run_store=run_store)["spec"])

    revised_draft = _current_revision_draft(current).model_copy(update={"rebalance_frequency": RebalanceFrequency.QUARTERLY})
    llm = fake_llm({"StrategySpecRevisionDraft": [revised_draft]})
    result = await revise_spec_draft(spec_run_id, ReviseSpecRequest(instruction="use quarterly rebalancing"), run_store=run_store, llm=llm, principal=PRINCIPAL)

    assert result["spec"]["rebalance_frequency"] == "quarterly"
    assert result["approved"] is False
    history = get_spec_draft(spec_run_id, run_store=run_store)["history"]
    assert len(history) == 1
    assert history[0]["comment"] == "use quarterly rebalancing"


async def test_backtest_rejected_without_approval(tmp_path, fake_llm):
    run_store = _run_store(tmp_path)
    spec_run_id = await _drafted_spec_run_id(run_store, fake_llm)

    with pytest.raises(HTTPException) as exc_info:
        run_backtest_from_spec(
            spec_run_id, BacktestRequest(tickers=["T0"], prices_ref="unused.csv"), run_store=run_store
        )
    assert exc_info.value.status_code == 403


def _write_price_csv(path, n_months=48, seed=11):
    rng = random.Random(seed)
    tickers = [f"T{i}" for i in range(15)]
    dates = []
    year, month = 1965, 1
    for _ in range(n_months):
        dates.append(f"{year}-{month:02d}-01")
        month += 1
        if month > 12:
            month, year = 1, year + 1
    prices = {t: [100.0] for t in tickers}
    for t in tickers:
        for _ in range(n_months - 1):
            prices[t].append(prices[t][-1] * (1 + rng.gauss(0.01, 0.05)))
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", *tickers])
        for i, d in enumerate(dates):
            writer.writerow([d, *(round(prices[t][i], 4) for t in tickers)])
    return tickers


def _upload_file(data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename="f.csv")


async def _upload_prices(run_store, spec_run_id, tmp_path):
    prices_path = tmp_path / "p48.csv"
    tickers = _write_price_csv(prices_path)
    upload = await upload_price_dataset(spec_run_id, _upload_file(prices_path.read_bytes()), run_store=run_store, settings=_settings())
    return tickers, upload


async def test_full_flow_backtest_then_results_then_regime_report(tmp_path, fake_llm):
    run_store = _run_store(tmp_path)
    spec_run_id = await _drafted_spec_run_id(run_store, fake_llm)
    approve_spec_draft(spec_run_id, ApproveSpecRequest(), run_store=run_store, principal=PRINCIPAL)

    tickers, upload = await _upload_prices(run_store, spec_run_id, tmp_path)

    result = run_backtest_from_spec(
        spec_run_id,
        BacktestRequest(tickers=tickers, prices_ref=upload.ref, out_of_sample_start=None, out_of_sample_end=None),
        run_store=run_store,
    )
    run_id = result["run_id"]

    detail = get_replication_run(run_id, run_store=run_store)
    assert detail.spec.strategy_name == "6-6 momentum"
    assert detail.regime_report is None
    assert detail.sanity_check is None

    regime = trigger_regime_report(run_id, run_store=run_store)
    assert "buckets" in regime

    detail_after = get_replication_run(run_id, run_store=run_store)
    assert detail_after.regime_report is not None


def test_get_replication_run_404_for_unknown_run(tmp_path):
    run_store = _run_store(tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        get_replication_run("nope", run_store=run_store)
    assert exc_info.value.status_code == 404


async def test_trigger_sanity_check_appends_and_is_returned_on_next_fetch(tmp_path, fake_llm):
    from arp.replication.sanity_check import SanityCheckAssessment

    run_store = _run_store(tmp_path)
    spec_run_id = await _drafted_spec_run_id(run_store, fake_llm)
    approve_spec_draft(spec_run_id, ApproveSpecRequest(), run_store=run_store, principal=PRINCIPAL)
    tickers, upload = await _upload_prices(run_store, spec_run_id, tmp_path)
    result = run_backtest_from_spec(spec_run_id, BacktestRequest(tickers=tickers, prices_ref=upload.ref), run_store=run_store)
    run_id = result["run_id"]

    assessment = SanityCheckAssessment(plausible=True, findings=[], summary="Looks fine.")
    llm = fake_llm({"SanityCheckAssessment": [assessment]})
    response = await trigger_sanity_check(run_id, run_store=run_store, llm=llm)
    assert response["plausible"] is True

    detail = get_replication_run(run_id, run_store=run_store)
    assert detail.sanity_check is not None
    assert detail.sanity_check.summary == "Looks fine."


async def test_approve_keeps_the_latest_edit(tmp_path, fake_llm):
    run_store = _run_store(tmp_path)
    spec_run_id = await _drafted_spec_run_id(run_store, fake_llm)
    edited = StrategySpec.model_validate(get_spec_draft(spec_run_id, run_store=run_store)["spec"])
    edited.holding_period_months = 12
    update_spec_draft(spec_run_id, edited, run_store=run_store, principal=PRINCIPAL)

    approved = approve_spec_draft(spec_run_id, None, run_store=run_store, principal=PRINCIPAL)
    assert approved["spec"]["holding_period_months"] == 12
    again = approve_spec_draft(spec_run_id, None, run_store=run_store, principal=PRINCIPAL)
    assert again["spec"]["holding_period_months"] == 12
    state = get_spec_draft(spec_run_id, run_store=run_store)
    assert state["spec"]["holding_period_months"] == 12 and state["approved"] is True
    assert len(state["history"]) == 3


async def _approved(run_store, fake_llm) -> str:
    spec_run_id = await _drafted_spec_run_id(run_store, fake_llm)
    approve_spec_draft(spec_run_id, None, run_store=run_store, principal=PRINCIPAL)
    return spec_run_id


def _small_cap() -> Settings:
    return Settings(max_upload_bytes=1_000_000)


def _padded_price_csv(size: int) -> bytes:
    """A valid price file of exactly `size` bytes: two rows, then empty lines."""
    head = b"date,T0\n1965-01-01,1.5\n1965-02-01,1.6\n"
    return head + b"\n" * (size - len(head))


async def test_upload_over_the_cap_is_413_for_both_routes(tmp_path, fake_llm):
    run_store = _run_store(tmp_path)
    spec_run_id = await _drafted_spec_run_id(run_store, fake_llm)
    big = b"x" * 1_000_001
    for call in (
        lambda: upload_price_dataset(spec_run_id, _upload_file(big), run_store=run_store, settings=_small_cap()),
        lambda: upload_characteristics_dataset(spec_run_id, "x", _upload_file(big), run_store=run_store, settings=_small_cap()),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await call()
        assert exc_info.value.status_code == 413
        assert exc_info.value.detail == "File is larger than the 1 MB upload limit."


async def test_upload_of_exactly_the_cap_is_accepted(tmp_path, fake_llm):
    run_store = _run_store(tmp_path)
    spec_run_id = await _drafted_spec_run_id(run_store, fake_llm)
    data = _padded_price_csv(1_000_000)
    assert len(data) == 1_000_000
    upload = await upload_price_dataset(spec_run_id, _upload_file(data), run_store=run_store, settings=_small_cap())
    assert upload.ref == "prices.csv" and upload.rows == 2


async def test_refused_upload_keeps_the_earlier_file(tmp_path, fake_llm):
    run_store = _run_store(tmp_path)
    spec_run_id = await _approved(run_store, fake_llm)
    tickers, first = await _upload_prices(run_store, spec_run_id, tmp_path)
    with pytest.raises(HTTPException) as too_big:
        await upload_price_dataset(spec_run_id, _upload_file(b"x" * 1_000_001), run_store=run_store, settings=_small_cap())
    assert too_big.value.status_code == 413
    with pytest.raises(HTTPException) as bad:
        await upload_price_dataset(spec_run_id, _upload_file(b"date,T0\n1965-01-01,1.5\n1965-02-01,abc\n"), run_store=run_store, settings=_settings())
    assert bad.value.status_code == 400
    result = run_backtest_from_spec(spec_run_id, BacktestRequest(tickers=tickers, prices_ref=first.ref), run_store=run_store)
    assert "run_id" in result


async def test_upload_answers_the_file_name_and_what_it_holds(tmp_path, fake_llm):
    run_store = _run_store(tmp_path)
    spec_run_id = await _drafted_spec_run_id(run_store, fake_llm)
    tickers, upload = await _upload_prices(run_store, spec_run_id, tmp_path)
    assert upload.model_dump() == {"ref": "prices.csv", "tickers": tickers, "rows": 48, "first_date": "1965-01-01", "last_date": "1968-12-01"}


@pytest.mark.parametrize(
    ("data", "detail"),
    [
        (b"", "the file is empty."),
        (b"\n\n", "the file is empty."),
        (b"date,T0\n", "no data rows."),
        (b"date,T0\n\n\n", "no data rows."),
        (b"date\n1965-01-01\n", "needs a date column and at least one ticker column."),
        (b"date,\n1965-01-01,1\n", "needs a date column and at least one ticker column."),
        (b"date,T0\n1965-01-01,1.5\n1965-02-01,abc\n", 'row 3, column T0: "abc" is not a number.'),
        (b"date,T0\n01/31/1965,1.5\n", 'row 2: date "01/31/1965" does not start with YYYY-MM-DD.'),
        (b"date,T0\n1965-13-01,1.5\n", 'row 2: date "1965-13-01" does not start with YYYY-MM-DD.'),
        (b"\xff\xfe\x00", "not UTF-8 text."),
        (b"date,T0\n\n1965-01-01,abc\n", 'row 3, column T0: "abc" is not a number.'),
    ],
)
async def test_unusable_file_is_refused_with_the_reason(tmp_path, fake_llm, data, detail):
    run_store = _run_store(tmp_path)
    spec_run_id = await _drafted_spec_run_id(run_store, fake_llm)
    with pytest.raises(HTTPException) as exc_info:
        await upload_price_dataset(spec_run_id, _upload_file(data), run_store=run_store, settings=_settings())
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == f"Not a usable CSV: {detail}"


async def test_blank_cells_long_dates_bom_and_leading_empty_line_are_accepted(tmp_path, fake_llm):
    run_store = _run_store(tmp_path)
    spec_run_id = await _approved(run_store, fake_llm)
    data = b"\xef\xbb\xbf\ndate,T0,T1\n1965-01-31 00:00:00,1.5,\n1965-02-28 00:00:00,,2\n"
    upload = await upload_price_dataset(spec_run_id, _upload_file(data), run_store=run_store, settings=_settings())
    assert (upload.tickers, upload.rows, upload.first_date, upload.last_date) == (["T0", "T1"], 2, "1965-01-31", "1965-02-28")
    # The stored file reads back through the backtest's own reader, so the check and the reader agree.
    with pytest.raises(HTTPException) as exc_info:
        run_backtest_from_spec(spec_run_id, BacktestRequest(tickers=["ZZZ"], prices_ref="prices.csv"), run_store=run_store)
    assert exc_info.value.detail == "prices.csv: no column(s) for ['ZZZ']"


def _client(run_store) -> TestClient:
    app = FastAPI()
    app.include_router(replication.router)
    app.dependency_overrides[deps.get_run_store] = lambda: run_store
    app.dependency_overrides[current_user] = lambda: PRINCIPAL
    return TestClient(app)


_CHARACTERISTICS_CSV = b"date,T0\n1965-01-01,0.5\n"


@pytest.mark.parametrize(
    ("name", "ref"),
    [
        ("book to market", "characteristics_book_to_market.csv"),
        ("B%2FM", "characteristics_B_M.csv"),
        ("..%2F..%2Fx", f"characteristics_{'_' * 6}x.csv"),
        ("a" * 100, f"characteristics_{'a' * 100}.csv"),
    ],
)
async def test_characteristic_names_are_slugged_into_the_stored_file_name(tmp_path, fake_llm, name, ref):
    run_store = _run_store(tmp_path)
    spec_run_id = await _drafted_spec_run_id(run_store, fake_llm)
    res = _client(run_store).post(f"/api/replication/specs/{spec_run_id}/datasets/characteristics/{name}", files={"file": ("c.csv", _CHARACTERISTICS_CSV)})
    assert res.status_code == 200, res.text
    assert res.json()["ref"] == ref


async def test_characteristic_name_must_be_1_to_100_characters(tmp_path, fake_llm):
    run_store = _run_store(tmp_path)
    spec_run_id = await _drafted_spec_run_id(run_store, fake_llm)
    client = _client(run_store)
    base = f"/api/replication/specs/{spec_run_id}/datasets/characteristics/"
    empty = client.post(base, files={"file": ("c.csv", _CHARACTERISTICS_CSV)})
    assert (empty.status_code, empty.json()["detail"]) == (400, "Characteristic name is empty.")
    long = client.post(base + "a" * 101, files={"file": ("c.csv", _CHARACTERISTICS_CSV)})
    assert (long.status_code, long.json()["detail"]) == (400, "Characteristic name is longer than 100 characters.")


async def test_backtest_reads_only_the_specs_own_uploads(tmp_path, fake_llm):
    run_store = _run_store(tmp_path)
    spec_run_id = await _approved(run_store, fake_llm)
    other_run_id = await _drafted_spec_run_id(run_store, fake_llm)
    tickers, _ = await _upload_prices(run_store, other_run_id, tmp_path)
    outside = tmp_path / "outside.csv"
    _write_price_csv(outside)

    def refused(ref, expected):
        with pytest.raises(HTTPException) as exc_info:
            run_backtest_from_spec(spec_run_id, BacktestRequest(tickers=tickers, prices_ref=ref), run_store=run_store)
        assert (exc_info.value.status_code, exc_info.value.detail) == (400, f"Data file not found: {expected}")

    refused("prices.csv", "prices.csv")  # nothing uploaded for this spec yet
    refused(f"../{other_run_id}/prices.csv", "prices.csv")  # another spec's upload
    refused(str(outside), "outside.csv")
    refused("/etc/passwd", "passwd")
    refused("characteristics_x.csv", "characteristics_x.csv")
    refused("prices.csv/", "")


async def test_backtest_refuses_a_missing_or_foreign_characteristics_file(tmp_path, fake_llm):
    run_store = _run_store(tmp_path)
    spec_run_id = await _approved(run_store, fake_llm)
    tickers, upload = await _upload_prices(run_store, spec_run_id, tmp_path)
    for refs, expected in (({"b": "characteristics_b.csv"}, "characteristics_b.csv"), ({"b": "/etc/passwd"}, "passwd")):
        with pytest.raises(HTTPException) as exc_info:
            run_backtest_from_spec(spec_run_id, BacktestRequest(tickers=tickers, prices_ref=upload.ref, characteristics_refs=refs), run_store=run_store)
        assert exc_info.value.detail == f"Data file not found: {expected}"


async def test_backtest_errors_name_the_file_not_the_server_path(tmp_path, fake_llm):
    run_store = _run_store(tmp_path)
    spec_run_id = await _approved(run_store, fake_llm)
    _, upload = await _upload_prices(run_store, spec_run_id, tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        run_backtest_from_spec(spec_run_id, BacktestRequest(tickers=["ZZZ"], prices_ref=upload.ref), run_store=run_store)
    assert (exc_info.value.status_code, exc_info.value.detail) == (400, "prices.csv: no column(s) for ['ZZZ']")
