"""Starting universes for Index Construction (spec index-starting-universe, PR 1: AC-1 to AC-42).

DAX means `data/holdings/DAX.xlsx` as committed. "No dataset" points `simulated_esg_path` at a missing file;
"the fixture dataset" is a CSV with the showcase dataset's full header and one row for SAP.
"""

from __future__ import annotations

import csv
from pathlib import Path

import openpyxl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.deps import get_decision_store, get_index_store, settings_dep
from arp.api.routers import index as index_router
from arp.config import REPO_ROOT, Settings
from arp.schemas.common import CompanyRef
from arp.schemas.decision import PublishedDecision, PublishedRow
from arp.schemas.portfolio import Holding, Portfolio, SecurityRef
from arp.storage.decision_store import DecisionStore
from arp.storage.index_store import IndexStore
from arp.storage.portfolio_store import PortfolioStore

SAP = "isin_DE0007164600"
DAX_DATE = "2026-11-02"
RISK_REFUSAL = (
    "Risk model: a loaded starting universe has no returns history, so tracking-error methods cannot run on it. "
    "Use the built-in demo universe, or send a returns_panel."
)
# showcase-portfolio-data's "Columns", in order.
DATASET_HEADER = [
    "isin", "company_id", "name", "country", "sector", "files", "data_status",
    "climate_scope1_tco2e", "climate_scope2_tco2e", "climate_scope3_tco2e", "climate_carbon_intensity",
    "climate_evic_eur_m", "climate_revenue_eur_m", "climate_green_revenue_pct",
    "esg_e_score", "esg_s_score", "esg_g_score", "esg_score", "esg_trend", "controversy_level",
    "coal_revenue_pct", "oil_revenue_pct", "gas_revenue_pct", "high_intensity_power_revenue_pct",
    "tobacco_revenue_pct", "weapons_revenue_pct", "alcohol_revenue_pct", "gambling_revenue_pct",
    "controversial_weapons", "norms_violation", "severe_controversy",
    "ghg_intensity", "green_revenue_pct", "transition_score", "lct_score", "lct_category",
    "transition_grade", "transition_grade_label",
]  # fmt: skip


@pytest.fixture
def env(tmp_path: Path):
    settings = Settings(
        holdings_dir=REPO_ROOT / "data" / "holdings",
        simulated_esg_path=tmp_path / "no_dataset.csv",
    )
    portfolios = PortfolioStore(tmp_path / "portfolios")
    decisions = DecisionStore(tmp_path / "frameworks")
    app = FastAPI()
    app.include_router(index_router.router)
    app.dependency_overrides[get_index_store] = lambda: IndexStore(tmp_path / "indices")
    app.dependency_overrides[get_decision_store] = lambda: decisions
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[index_router.portfolio_store_getter] = lambda: (lambda: portfolios)
    return TestClient(app), settings, portfolios, decisions, tmp_path


def _use_fixture_dataset(settings: Settings, tmp_path: Path) -> None:
    row = {c: "1" for c in DATASET_HEADER}
    row.update(
        isin="DE0007164600", company_id=SAP, name="SAP SE", country="Germany", files="DAX", data_status="simulated",
        esg_score="7.25", coal_revenue_pct="0", norms_violation="false", controversial_weapons="false",
        severe_controversy="false", lct_category="neutral", transition_grade="B",
        transition_grade_label="Credible", sector="Information Technology",
    )  # fmt: skip
    path = tmp_path / "esg_simulated.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=DATASET_HEADER)
        writer.writeheader()
        writer.writerow(row)
    settings.simulated_esg_path = path


def _xlsx(directory: Path, stem: str, title: str, lines: list[tuple[str, str, float | str]]) -> None:
    """A file in DAX layout: (name, Type of Security, Weighting) per line."""
    directory.mkdir(exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title
    ws.append([None])
    ws.append(["disclaimer"])
    ws.append([None])
    ws.append([None, "Name", "ISIN", "Country", "Currency", "Exchange", "Type of Security", "Rating",
               "Primary Listing", "Industry Classification", "Weighting"])  # fmt: skip
    for i, (name, sec_type, weight) in enumerate(lines):
        ws.append([i + 1, name, f"DE000000000{i}", "Deutschland", "EUR", "-", sec_type, "-", "-", "Technologie", weight])
    wb.save(directory / f"{stem}.xlsx")


def _spec(**solver) -> dict:
    spec = {}
    if solver:
        spec["constraints"] = {"solver": solver}
    return spec


def _run(client: TestClient, n: int, review_date: str = DAX_DATE, **body):
    body.setdefault("spec", _spec())
    return client.post(
        "/api/index/run",
        json={"index_id": f"ac{n}_index", "review_date": review_date, "use_prior_state": False, **body},
    )


def _dax(client: TestClient) -> dict:
    response = client.get("/api/index/universes/file:DAX")
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------------ listing


def test_ac1_ac2_the_list_starts_with_demo_then_files_sorted_by_stem(env):
    client = env[0]
    response = client.get("/api/index/universes")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body[0] == {"universe_id": "demo", "label": "Built-in demo universe (60 synthetic companies)", "kind": "demo", "as_of_date": None}
    assert {"universe_id": "file:DAX", "label": "DAX.xlsx", "kind": "file", "as_of_date": DAX_DATE} in body
    files = [e["universe_id"] for e in body[1:] if e["kind"] == "file"]
    assert [e["universe_id"] for e in body[1 : 1 + len(files)]] == files
    assert files == sorted(files) and len(files) == len(list((REPO_ROOT / "data" / "holdings").glob("*.xlsx")))


def test_ac12_a_file_with_a_bad_sheet_title_is_listed_without_a_date(env):
    client, settings, _, _, tmp_path = env
    _xlsx(tmp_path / "h", "X", "Sheet1", [("A", "Aktien", 0.5)])
    settings.holdings_dir = tmp_path / "h"
    body = client.get("/api/index/universes").json()
    assert {"universe_id": "file:X", "label": "X.xlsx", "kind": "file", "as_of_date": None} in body


def _portfolio_p1(store: PortfolioStore) -> str:
    """AC-25: c_a through two equity securities (30 + 20), c_b (45), cash linked to c_cash (5), unlinked equity (1)."""
    as_of = "2026-10-31"
    store.save_portfolio(Portfolio(portfolio_id="p1", name="My fund"))
    store.save_portfolio(Portfolio(portfolio_id="p0", name="Empty fund"))
    store.save_company(CompanyRef(company_id="c_a", name="Alpha AG", sector="Industrials", country="Germany"))
    store.save_company(CompanyRef(company_id="c_b", name="Beta SA"))
    store.save_company(CompanyRef(company_id="c_cash", name="Cash Bank"))
    securities = [
        ("s_a1", "equity", "c_a", 30.0), ("s_a2", "equity", "c_a", 20.0), ("s_b", "equity", "c_b", 45.0),
        ("s_cash", "cash", "c_cash", 5.0), ("s_x", "equity", None, 1.0),
    ]  # fmt: skip
    holdings = []
    for sid, asset_class, company_id, weight in securities:
        store.save_security(SecurityRef(security_id=sid, name=sid, asset_class=asset_class, currency="EUR", company_id=company_id))
        holdings.append(Holding(holder_id="p1", security_id=sid, as_of_date=as_of, weight_pct=weight, market_value_eur=weight))
    store.save_snapshot("p1", as_of, holdings)
    return as_of


def test_ac28_portfolios_with_a_snapshot_come_after_the_files(env):
    client, _, store, _, _ = env
    as_of = _portfolio_p1(store)
    body = client.get("/api/index/universes").json()
    portfolios = [e for e in body if e["universe_id"].startswith("portfolio:")]
    assert portfolios == [{"universe_id": "portfolio:p1", "label": "My fund", "kind": "portfolio", "as_of_date": as_of}]
    assert body.index(portfolios[0]) > max(i for i, e in enumerate(body) if e["kind"] == "file")


# ------------------------------------------------------------------ one universe


def test_ac3_to_ac7_dax_without_the_dataset(env):
    body = _dax(env[0])
    assert body["company_count"] == 40
    assert body["notes"] == [
        "Starting universe: DAX.xlsx, holdings as of 2026-11-02, 40 companies.",
        "Dropped 3 lines: 2 cash, 1 other asset class, 0 zero or negative weight, 0 without a weight, 0 not linked to a company.",
        "Size is a weight proxy: each company's free-float market cap is its weight × an assumed EUR 100,000,000, at price 1. It is not market data.",
        "Simulated ESG data: not available; loaded companies carry no ESG fields.",
    ]
    assert body["fields"] == {"metrics": ["float_mcap", "free_float_factor", "price", "shares_outstanding"], "flags": [], "categories": ["country", "sector"]}
    assert (body["universe_id"], body["label"], body["kind"], body["as_of_date"]) == ("file:DAX", "DAX.xlsx", "file", DAX_DATE)


def test_demo_detail_has_the_catalogue_fields_and_no_notes(env):
    client = env[0]
    body = client.get("/api/index/universes/demo").json()
    assert body["company_count"] == 60 and body["notes"] == []
    assert body["fields"] == client.get("/api/index/catalogue").json()["fields"]


@pytest.mark.parametrize(
    ("path", "universe_id"),
    [("file:NOPE", "file:NOPE"), ("file:..%2Fconfig%2Fusers", "file:../config/users"), ("portfolio:nope", "portfolio:nope"), ("nope", "nope")],
)
def test_ac8_ac9_unknown_universes_are_a_404(env, path, universe_id):
    response = env[0].get(f"/api/index/universes/{path}")
    assert response.status_code == 404
    assert response.json()["detail"] == f"Unknown starting universe: {universe_id}"


def test_ac11_a_file_without_usable_lines_is_refused(env):
    client, settings, _, _, tmp_path = env
    _xlsx(tmp_path / "h", "X", DAX_DATE, [("Cash", "Cash", 0.5), ("A", "Aktien", -0.01), ("B", "Aktien", "N/A")])
    settings.holdings_dir = tmp_path / "h"
    response = client.get("/api/index/universes/file:X")
    assert response.status_code == 422
    assert response.json()["detail"] == "X.xlsx: no equity lines with a positive weight."


def test_ac13_a_bad_sheet_title_is_named_on_load(env):
    client, settings, _, _, tmp_path = env
    _xlsx(tmp_path / "h", "X", "Sheet1", [("A", "Aktien", 0.5)])
    settings.holdings_dir = tmp_path / "h"
    response = client.get("/api/index/universes/file:X")
    assert response.status_code == 422
    assert response.json()["detail"] == "X.xlsx: sheet title 'Sheet1' is not an ISO date (YYYY-MM-DD)"


def test_ac25_portfolio_lines_are_bucketed_and_summed_per_company(env):
    client, _, store, _, _ = env
    _portfolio_p1(store)
    body = client.get("/api/index/universes/portfolio:p1").json()
    assert body["company_count"] == 2
    assert body["notes"][1] == (
        "Dropped 2 lines: 1 cash, 0 other asset class, 0 zero or negative weight, 0 without a weight, 1 not linked to a company."
    )


def test_ac29_ac30_the_fixture_dataset_joins(env):
    client, settings, _, _, tmp_path = env
    _use_fixture_dataset(settings, tmp_path)
    body = _dax(client)
    assert body["notes"][3] == "Simulated ESG data: matched 1 of 40 companies."
    assert body["fields"]["categories"] == ["country", "lct_category", "sector", "transition_grade"]
    assert body["fields"]["flags"] == ["controversial_weapons", "norms_violation", "severe_controversy"]
    assert "transition_grade_label" not in body["fields"]["categories"]
    assert not any(m.startswith("climate_") for m in body["fields"]["metrics"])


# ------------------------------------------------------------------ runs


def _constituent(result: dict, company_id: str) -> dict:
    return next(c for c in result["constituents"] if c["company_id"] == company_id)


def test_ac14_to_ac16_a_dax_run(env):
    client = env[0]
    response = _run(client, 14, universe="file:DAX")
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["constituents"]) == 40
    sap = _constituent(result, SAP)
    assert sap["name"] == "SAP"
    assert sap["weight"] == pytest.approx(0.1176544801, abs=1e-9)
    assert sap["price"] == 1.0
    assert result["input_notes"][0:3] == _dax(client)["notes"][0:3]


def test_ac17_a_saved_review_says_where_its_companies_came_from(env):
    client = env[0]
    assert _run(client, 17, universe="file:DAX", persist=True).status_code == 200
    review = client.get(f"/api/index/ac17_index/reviews/{DAX_DATE}").json()
    assert review["input_notes"][0] == "Starting universe: DAX.xlsx, holdings as of 2026-11-02, 40 companies."


def test_ac18_holdings_after_the_review_date_are_refused(env):
    response = _run(env[0], 18, review_date="2026-10-01", universe="file:DAX")
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "DAX.xlsx holds holdings as of 2026-11-02, after the review date 2026-10-01: "
        "a review cannot use holdings that did not exist yet."
    )


@pytest.mark.parametrize("universe", ["file:DAX", "demo"])
def test_ac19_ac20_universe_and_candidates_are_exclusive(env, universe):
    candidate = {"company_id": "x", "name": "X", "price": 1.0, "shares_outstanding": 1.0}
    response = _run(env[0], 19, universe=universe, candidates=[candidate])
    assert response.status_code == 400
    assert response.json()["detail"] == "Send either universe or candidates, not both."


@pytest.mark.parametrize("universe", ["file:NOPE", "file:../../config/users"])
def test_ac10_ac21_unknown_universe_runs_are_a_404(env, universe):
    response = _run(env[0], 21, universe=universe)
    assert response.status_code == 404
    assert response.json()["detail"] == f"Unknown starting universe: {universe}"


def test_ac22_tracking_error_on_a_loaded_universe_is_refused(env):
    response = _run(env[0], 22, universe="file:DAX", spec=_spec(method="min_tracking_error"))
    assert response.status_code == 422
    assert response.json()["detail"] == RISK_REFUSAL


def test_ac23_a_te_budget_on_sent_candidates_is_refused(env):
    candidates = [{"company_id": f"c{i}", "name": f"C{i}", "price": 1.0, "shares_outstanding": 10.0 + i} for i in range(3)]
    response = _run(env[0], 23, candidates=candidates, spec=_spec(tracking_error_budget=0.02))
    assert response.status_code == 422
    assert response.json()["detail"] == RISK_REFUSAL


def test_ac24_levels_of_a_loaded_review_say_why_there_are_none(env):
    client = env[0]
    assert _run(client, 24, universe="file:DAX", persist=True).status_code == 200
    response = client.get(f"/api/index/ac24_index/levels/{DAX_DATE}")
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "No level series: this review ran on a loaded starting universe, which has no price history "
        "(its prices are a weight proxy)."
    )


def test_ac26_ac27_a_portfolio_run(env):
    client, _, store, _, _ = env
    as_of = _portfolio_p1(store)
    response = _run(client, 26, review_date=as_of, universe="portfolio:p1")
    assert response.status_code == 200, response.text
    result = response.json()
    assert _constituent(result, "c_a")["weight"] == pytest.approx(0.5263157895, abs=1e-9)
    assert _constituent(result, "c_b")["weight"] == pytest.approx(0.4736842105, abs=1e-9)
    assert _constituent(result, "c_a")["name"] == "Alpha AG"


def _esg_screen(missing: str) -> dict:
    return {"screens": [{"type": "metric_threshold", "field": "esg_score", "min_value": 5, "missing": missing}]}


def test_ac31_a_metric_screen_on_the_dataset(env):
    client, settings, _, _, tmp_path = env
    _use_fixture_dataset(settings, tmp_path)
    result = _run(client, 31, universe="file:DAX", spec=_esg_screen("fail")).json()
    assert [c["company_id"] for c in result["constituents"]] == [SAP]


def test_ac32_a_category_screen_on_the_grade(env):
    client, settings, _, _, tmp_path = env
    _use_fixture_dataset(settings, tmp_path)
    spec = {"screens": [{"type": "category_screen", "field": "transition_grade", "allow": ["B"], "missing": "fail"}]}
    result = _run(client, 32, universe="file:DAX", spec=spec).json()
    assert [c["company_id"] for c in result["constituents"]] == [SAP]


def test_ac33_without_the_dataset_an_esg_rule_blocks(env):
    response = _run(env[0], 33, universe="file:DAX", spec=_esg_screen("block"))
    assert response.status_code == 422
    assert response.json()["detail"].startswith("Data quality block:")
    assert "esg_score" in response.json()["detail"]


def test_ac34_decision_notes_follow_the_universe_notes(env):
    client, _, _, decisions, _ = env
    snapshot = decisions.save_published(
        PublishedDecision(
            framework_id="fw", framework_version=1, framework_name="Fw", dataset_id="d", dataset_name="d",
            id_column="company_id", published_by="Test", published_at="2026-11-01T00:00:00+00:00",
            rows=[PublishedRow(entity_id=SAP, name="SAP", score=1.0, tier=1)],
        )
    )  # fmt: skip
    response = _run(client, 34, universe="file:DAX", decision_snapshot_ids=[snapshot.snapshot_id])
    assert response.status_code == 200, response.text
    assert response.json()["input_notes"][4].endswith("matched 1 of 40 candidates.")


def test_ac41_the_dataset_sector_replaces_the_file_sector(env):
    client, settings, _, _, tmp_path = env
    _use_fixture_dataset(settings, tmp_path)
    assert _constituent(_run(client, 41, universe="file:DAX").json(), SAP)["sector"] == "Information Technology"


def test_ac42_without_the_dataset_the_file_labels_are_translated(env):
    sap = _constituent(_run(env[0], 42, universe="file:DAX").json(), SAP)
    assert (sap["sector"], sap["country"]) == ("Technology", "Germany")


# ------------------------------------------------------------------ must not change


def test_ac36_demo_by_name_equals_the_default(env):
    client = env[0]
    for name in [p["name"] for p in client.get("/api/index/catalogue").json()["presets"]]:
        spec = client.get(f"/api/index/presets/{name}").json()
        plain = _run(client, 36, review_date="2026-03-31", spec=spec).json()
        named = _run(client, 36, review_date="2026-03-31", spec=spec, universe="demo").json()
        for body in (plain, named):
            body.pop("created_at")
        assert named == plain


def test_ac38_ac40_demo_tracking_error_runs_still_use_the_demo_risk_model(env):
    client = env[0]
    spec = _spec(method="min_tracking_error")
    plain = _run(client, 38, review_date="2026-03-31", spec=spec)
    empty = _run(client, 38, review_date="2026-03-31", spec=spec, candidates=[])
    assert (plain.status_code, empty.status_code) == (200, 200), plain.text  # 200 on main too
    a, b = plain.json(), empty.json()
    a.pop("created_at"), b.pop("created_at")
    assert a == b


def test_a_file_isin_that_cannot_form_a_company_id_is_refused(env):
    client, settings, _, _, tmp_path = env
    _xlsx(tmp_path / "h", "X", DAX_DATE, [("A", "Aktien", 0.5)])
    wb = openpyxl.load_workbook(tmp_path / "h" / "X.xlsx")
    wb.active["C5"] = "../x"
    wb.save(tmp_path / "h" / "X.xlsx")
    settings.holdings_dir = tmp_path / "h"
    response = client.get("/api/index/universes/file:X")
    assert response.status_code == 422
    assert "cannot form a valid company_id" in response.json()["detail"]


def test_one_isin_listed_twice_is_one_company(env):
    client, settings, _, _, tmp_path = env
    _xlsx(tmp_path / "h", "X", DAX_DATE, [("A", "Aktien", 0.25), ("A2", "Aktien", 0.5)])
    wb = openpyxl.load_workbook(tmp_path / "h" / "X.xlsx")
    wb.active["C6"] = wb.active["C5"].value
    wb.save(tmp_path / "h" / "X.xlsx")
    settings.holdings_dir = tmp_path / "h"
    assert client.get("/api/index/universes/file:X").json()["company_count"] == 1


# ------------------------------------------------------------------ review findings


@pytest.mark.parametrize("review_date", ["20261101", "2026-11-1"])
def test_look_ahead_cannot_be_bypassed_with_a_non_padded_date(env, review_date):
    response = _run(env[0], 18, review_date=review_date, universe="file:DAX")
    assert response.status_code == 400, response.text


def test_an_unreadable_xlsx_is_a_422_naming_the_file(env):
    client, settings, _, _, tmp_path = env
    (tmp_path / "h").mkdir()
    (tmp_path / "h" / "~$DAX.xlsx").write_bytes(b"not a zip")
    settings.holdings_dir = tmp_path / "h"
    response = client.get("/api/index/universes/file:~$DAX")
    assert response.status_code == 422
    assert response.json()["detail"] == "~$DAX.xlsx: not a readable .xlsx file"


def _dataset_with_esg_score(settings: Settings, tmp_path: Path, value: str) -> None:
    _use_fixture_dataset(settings, tmp_path)
    text = settings.simulated_esg_path.read_text(encoding="utf-8")
    settings.simulated_esg_path.write_text(text.replace(",7.25,", f",{value},"), encoding="utf-8")


def test_a_nan_dataset_cell_is_not_joined(env):
    client, settings, _, _, tmp_path = env
    _dataset_with_esg_score(settings, tmp_path, "nan")
    assert "esg_score" not in _dax(client)["fields"]["metrics"]  # so no screen reads NaN as a value


def test_a_non_numeric_dataset_cell_names_the_file_and_column(env):
    client, settings, _, _, tmp_path = env
    _dataset_with_esg_score(settings, tmp_path, "n/a")
    response = client.get("/api/index/universes/file:DAX")
    assert response.status_code == 422
    assert response.json()["detail"] == "esg_simulated.csv: esg_score of isin_DE0007164600 is not a number: 'n/a'"
