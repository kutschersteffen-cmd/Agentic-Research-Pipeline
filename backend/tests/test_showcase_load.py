"""`arp showcase load` (spec showcase-portfolio-data, PR 2) on seven small holdings files and the dataset simulated
from them: the import, the simulated history, the simulated ESG observations and the six monthly runs."""

from __future__ import annotations

import csv

import pytest

from arp.bi.published import GRADE_LETTERS, month_end
from arp.config import Settings
from arp.portfolio import datapoint_mapping
from arp.portfolio.climate.esg_intake import FIELD_IDS as CLIMATE_FIELD_IDS
from arp.portfolio.loads import latest_load
from arp.schemas.portfolio import DataPointObservation
from arp.showcase.load import MONTHS, load
from arp.showcase.schema import FIELD_IDS
from arp.showcase.simulate import FILE_ORDER, GRADES, read_holdings, simulate, write_dataset
from arp.storage.portfolio_store import PortfolioStore
from tests.test_constituent_import import _xlsx

pytestmark = pytest.mark.usefixtures("pg")  # run_month needs Postgres

PORTFOLIOS = {
    "portfolio_dax", "portfolio_euro_stoxx_50", "portfolio_msci_em", "portfolio_msci_europe", "portfolio_msci_world",
    "portfolio_sp500", "portfolio_ai_big_data",
}
# ten companies of one sector: grades A 1, B 2, C 3, D 2, E 1, F 1
ISINS = [f"US00000000{i:02d}" for i in range(10)]


def _rows(isins, english=False, sector="Informationstechnologie"):
    country, kind, sector = (
        ("United States", "Equities", "Technology") if english else ("Vereinigte Staaten von Amerika", "Aktien", sector)
    )
    weight = 0.98 / len(isins)
    return [(f"Company {i[-2:]}", i, country, "USD", kind, sector, weight) for i in isins] + [("Cash EUR", "CASH_EUR", "-", "EUR", "Cash", "-", 0.02)]


@pytest.fixture
def env(tmp_path):
    holdings = tmp_path / "holdings"
    holdings.mkdir()
    for stem in FILE_ORDER:
        isins = ISINS if stem == "MSCI_World" else ISINS[:3]
        legacy = "Basiskonsumgüter" if stem in ("DAX", "EURO_STOXX_50") else "Informationstechnologie"  # the older scheme
        _xlsx(holdings, _rows(isins, english=stem == "AI_Big_Data", sector=legacy), title="2026-11-12" if stem == "AI_Big_Data" else "2026-11-02", name=f"{stem}.xlsx")
    dataset = tmp_path / "esg_simulated.csv"
    write_dataset(simulate(read_holdings(holdings), []), dataset)
    settings = Settings(
        engagements_dir=tmp_path / "eng", stewardship_streams_dir=tmp_path / "streams", frameworks_dir=tmp_path / "fw", runs_dir=tmp_path / "runs",
    )
    store = PortfolioStore(tmp_path / "pf")
    with dataset.open(newline="", encoding="utf-8") as fh:
        rows = {r["transition_grade"]: r for r in csv.DictReader(fh)}  # one company per grade
    return store, settings, holdings, dataset, rows


def _run(env, monkeypatch=None):
    store, settings, holdings, dataset, _ = env
    lines, published = [], {}
    if monkeypatch:
        monkeypatch.setattr(store, "publish_rows", lambda d, m, rows: published.__setitem__((d, m), rows), raising=False)
    ok = load(store, settings, holdings, dataset, lines.append)
    return ok, lines, published


def _counts(store):
    events = [e for e in store.list_governance_events() if e.get("event_type") == "load_recorded"]
    observations = sum(len(store.load_observations(c, f)) for c, f in store.list_observation_keys())
    snapshots = sum(len(store.list_snapshot_dates(p.portfolio_id)) for p in store.list_portfolios())
    return len(store.list_portfolios()), snapshots, len(events), observations


def test_every_step_reports_ok_and_the_six_months_run(env, monkeypatch):
    ok, lines, published = _run(env, monkeypatch)
    assert ok and [line.split(":")[0] for line in lines] == [
        "ok import", "ok history", "ok esg", "ok scores", *(f"ok run {m}" for m in MONTHS),
    ]
    assert lines[4].startswith("ok run 2026-06: ") and lines[4].endswith(" triggers") and " alerts, " in lines[4]
    for month in MONTHS:
        assert {r["portfolio_id"] for r in published[("portfolio_climate_metrics", month)]} == PORTFOLIOS


def test_history_is_five_rescaled_month_ends_labelled_simulated(env):
    store = env[0]
    assert _run(env)[0]
    assert {p.portfolio_id for p in store.list_portfolios() if "history:simulated" in p.tags} == PORTFOLIOS
    assert "fund_isin:IE00BGV5VN51" in store.get_portfolio("portfolio_ai_big_data").tags
    assert store.get_company(f"isin_{ISINS[0]}").sector == "Information Technology"  # MSCI World's label, not the DAX one
    assert store.list_snapshot_dates("portfolio_dax") == ["2026-06-30", "2026-07-31", "2026-08-31", "2026-09-30", "2026-10-31", "2026-11-02"]
    assert store.list_snapshot_dates("portfolio_ai_big_data")[-1] == "2026-11-12"
    file, july, august = (
        {h.security_id: h for h in store.load_snapshot("portfolio_msci_world", d)} for d in ("2026-11-02", "2026-07-31", "2026-08-31")
    )
    assert set(july) == set(file)
    assert all(0.90 <= july[s].weight_pct / file[s].weight_pct <= 1.11 for s in file)
    assert sum(h.weight_pct for h in july.values()) == pytest.approx(sum(h.weight_pct for h in file.values()), abs=1e-4)
    assert any(july[s].weight_pct != august[s].weight_pct for s in file)
    h = july[ISINS[0]]
    assert h.as_of_date == "2026-07-31" and h.market_value_eur == pytest.approx(h.weight_pct / 100 * 100_000_000)
    for month in MONTHS[:-1]:
        rec = latest_load(store, "holdings", "portfolio_sp500", month)
        assert rec.status == "ok" and rec.detail == "simulated history from SP500.xlsx"
    assert latest_load(store, "holdings", "portfolio_sp500", "2026-11").detail == "constituent import SP500.xlsx"


def test_esg_values_drift_by_grade_and_carry_the_simulated_source(env, monkeypatch):
    store, *_, rows = env
    ok, _, published = _run(env, monkeypatch)
    assert ok
    for month in MONTHS:
        rec = latest_load(store, "esg", "simulated", month)
        day = "2026-11-02" if month == "2026-11" else month_end(month)
        assert (rec.status, rec.at[:10], rec.detail) == ("ok", day, "simulated ESG from esg_simulated.csv")

    def profile(month, company_id, field_id):
        (row,) = [r for r in published[("company_profile", month)] if (r["company_id"], r["field_id"]) == (company_id, field_id)]
        return row

    a, f = rows["A"], rows["F"]
    june = profile("2026-06", a["company_id"], "climate_scope1_tco2e")
    assert june["value"] == pytest.approx(float(a["climate_scope1_tco2e"]) * 1.05, rel=1e-3)
    assert (june["source"], june["as_of"]) == ("simulated", "2026-06-30")
    assert profile("2026-10", a["company_id"], "climate_carbon_intensity")["value"] == pytest.approx(float(a["climate_carbon_intensity"]) * 1.01, rel=1e-3)
    assert profile("2026-06", a["company_id"], "climate_scope3_tco2e")["value"] == float(a["climate_scope3_tco2e"])  # only scope 1, 2 and intensity drift
    for month in ("2026-06", "2026-11"):
        assert profile(month, f["company_id"], "climate_scope1_tco2e")["value"] == float(f["climate_scope1_tco2e"])
    november = profile("2026-11", a["company_id"], "climate_scope1_tco2e")
    assert (november["value"], november["source"], november["as_of"]) == (float(a["climate_scope1_tco2e"]), "simulated", "2026-11-02")


def test_the_25_score_fields_are_published_for_november_only(env, monkeypatch):
    rows = env[-1]
    ok, _, published = _run(env, monkeypatch)
    assert ok
    a = rows["A"]
    november = {r["field_id"]: r for r in published[("company_profile", "2026-11")] if r["company_id"] == a["company_id"]}
    assert set(FIELD_IDS) <= set(november) and all(november[f]["source"] == "simulated" for f in FIELD_IDS)
    assert (november["transition_grade"]["value"], november["transition_grade_label"]["value"]) == ("A", "Leader")
    assert november["peer_group"]["value"] == "Information Technology"
    assert november["norms_violation"]["value"] is False and november["esg_score"]["value"] == float(a["esg_score"])
    october = {r["field_id"] for r in published[("company_profile", "2026-10")] if r["company_id"] == a["company_id"]}
    assert not october & set(FIELD_IDS)


def test_grade_weights_are_shares_of_the_graded_weight(env, monkeypatch):
    assert "".join(g[0] for g in GRADES) == GRADE_LETTERS  # published.py keeps its own copy of the letters
    ok, _, published = _run(env, monkeypatch)
    assert ok
    (world,) = [r for r in published[("portfolio_climate_metrics", "2026-11")] if r["portfolio_id"] == "portfolio_msci_world"]
    # ten equal weights graded A 1, B 2, C 3, D 2, E 1, F 1; the cash line has no company, so no grade
    shares = {g: world[f"grade_{g}_weight_pct"] for g in "abcdef"}
    assert shares == pytest.approx({"a": 10, "b": 20, "c": 30, "d": 20, "e": 10, "f": 10})
    for r in published[("portfolio_climate_metrics", "2026-11")]:
        assert sum(r[f"grade_{g}_weight_pct"] for g in "abcdef") == pytest.approx(100)
    (june,) = [r for r in published[("portfolio_climate_metrics", "2026-06")] if r["portfolio_id"] == "portfolio_msci_world"]
    assert all(june[f"grade_{g}_weight_pct"] is None for g in "abcdef")  # the grade is observed for 2026-11 only


def test_dataset_companies_open_on_the_company_page_with_their_simulated_values(env):
    from arp.api.routers.companies import get_simulated_esg
    from arp.db import company_view
    from arp.db.companies import ensure_universe_company
    from arp.db.session import transaction

    store, *_, rows = env
    assert _run(env)[0]
    a = rows["A"]
    with transaction() as s:
        uuid = company_view.resolve_ref(s, f"UNIVERSE:{a['company_id']}")
        assert uuid is not None and company_view.resolve_ref(s, f"ISIN:{a['isin']}") == uuid
        assert [h.id for h in company_view.search(s, a["name"])] == [uuid]
    values = {o.field_id: o for o in get_simulated_esg(str(uuid), store)}
    assert set(values) == {*CLIMATE_FIELD_IDS, *FIELD_IDS} and {o.source for o in values.values()} == {"simulated"}
    assert values["transition_grade"].value == "A" and values["climate_scope1_tco2e"].value == float(a["climate_scope1_tco2e"])
    assert get_simulated_esg(f"UNIVERSE:{a['company_id']}", store) == list(values.values())
    with transaction() as s:
        other = ensure_universe_company(s, "not_simulated")
    assert get_simulated_esg(str(other), store) == []


def test_after_a_reload_with_a_changed_grade_the_card_shows_the_new_one(env):
    from arp.api.routers.companies import get_simulated_esg

    store, _, _, dataset, rows = env
    assert _run(env)[0]
    a = rows["A"]["company_id"]
    with dataset.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields, data = reader.fieldnames, list(reader)
    for r in data:
        if r["company_id"] == a:
            r["transition_grade"], r["transition_grade_label"] = "B", "Credible"
    with dataset.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fields)
        writer.writeheader()
        writer.writerows(data)
    assert _run(env)[0]
    card = {o.field_id: o.value for o in get_simulated_esg(f"UNIVERSE:{a}", store)}
    resolved = datapoint_mapping.resolve_field_value(store, a, "transition_grade", "2026-11-02").value
    assert (card["transition_grade"], card["transition_grade_label"], resolved) == ("B", "Credible", "B")


def test_a_second_run_changes_nothing(env):
    store = env[0]
    assert _run(env)[0]
    first = _counts(store)
    ok, lines, _ = _run(env)
    assert ok and _counts(store) == first
    assert lines[2].startswith("ok esg: 0 new") and lines[3].startswith("ok scores: 0 new")


def test_a_real_value_beats_the_simulated_one(env):
    store, *_, rows = env
    assert _run(env)[0]
    cid = rows["C"]["company_id"]
    store.append_observation(DataPointObservation(
        company_id=cid, field_id="climate_scope1_tco2e", field_name="Scope 1 GHG emissions", value=123.0, unit="tCO2e",
        period="2026-11", observed_at="2026-11-02T00:00:00+00:00", source="internal_api",
    ))
    obs = datapoint_mapping.resolve_field_value(store, cid, "climate_scope1_tco2e", "2026-11-30")
    assert (obs.source, obs.value) == ("internal_api", 123.0)


def test_a_missing_file_fails_the_import_step_and_stops(env):
    store, settings, holdings, dataset, _ = env
    (holdings / "DAX.xlsx").unlink()
    lines: list[str] = []
    assert load(store, settings, holdings, dataset, lines.append) is False
    assert len(lines) == 1 and lines[0].startswith("FAIL import: ") and "DAX.xlsx" in lines[0]


def test_the_command_exits_1_on_a_fail_line(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from arp.cli import app
    from arp.config import get_settings

    monkeypatch.setenv("ARP_PORTFOLIOS_DIR", str(tmp_path / "pf"))
    get_settings.cache_clear()
    result = CliRunner().invoke(app, ["showcase", "load", "--holdings-dir", str(tmp_path / "nowhere")])
    assert result.exit_code == 1 and "FAIL import: " in result.output


def test_the_simulated_schema_is_served_next_to_the_climate_schema():
    from fastapi.testclient import TestClient

    from arp.api.main import app

    body = TestClient(app).get("/api/climate/simulated-schema").json()
    assert body["schema_id"] == "simulated_esg" and body["name"] == "Simulated ESG"
    assert [f["field_id"] for f in body["fields"]] == FIELD_IDS and len(FIELD_IDS) == 25
    assert {f["field_id"] for f in body["fields"] if f["data_type"] == "boolean"} == {"controversial_weapons", "norms_violation", "severe_controversy"}
