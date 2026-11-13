"""Security review of PR #434: a simulated value (`arp showcase load`) must never stand in for a real one in the
readers that do not go through `datapoint_mapping.resolve_field_value`, nor be imported as a real provider's load."""

from __future__ import annotations

from arp.config import Settings
from arp.db.importer import _esg_loads
from arp.decision.sources import from_portfolio_snapshot
from arp.portfolio.climate.esg_intake import FIELD_IDS
from arp.portfolio.climate.schemas import FIELD_SCOPE1
from arp.portfolio.loads import LoadRecord, record_load
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import DataPointObservation, Holding, Portfolio, SecurityRef, SecurityResolution
from arp.showcase.load import _esg
from arp.stewardship.universe import from_portfolio
from arp.storage.portfolio_store import PortfolioStore

REAL, SIM_ONLY = "isin_US0378331005", "isin_DE0007164600"


def _store(tmp_path, real=True) -> PortfolioStore:
    """REAL has a real 2026-11 ESG load (1000.0 per field) and, written after it, the simulated values (7.0);
    SIM_ONLY has only simulated values."""
    store = PortfolioStore(tmp_path)
    store.save_portfolio(Portfolio(portfolio_id="fund", name="Fund"))
    holdings = []
    for cid in (REAL, SIM_ONLY):
        store.save_company(CompanyRef(company_id=cid, name=cid))
        store.save_security(SecurityRef(security_id=cid[5:], name=cid, isin=cid[5:], company_id=cid, asset_class="equity", currency="EUR"))
        store.save_resolution(SecurityResolution(security_id=cid[5:], company_id=cid, method="isin_exact", confidence=1.0))
        holdings.append(Holding(portfolio_id="fund", security_id=cid[5:], as_of_date="2026-11-30", quantity=1, price=100.0,
                                market_value=100.0, market_value_eur=100.0, weight_pct=50.0))
    store.save_snapshot("fund", "2026-11-30", holdings)
    if real:
        for fid in FIELD_IDS:
            store.append_observation(DataPointObservation(
                company_id=REAL, field_id=fid, field_name=fid, value=1000.0, period="2026-11",
                observed_at="2026-11-10T00:00:00+00:00", source="internal_api"))
        record_load(store, LoadRecord(kind="esg", source_id="default", month="2026-11", status="ok", content_hash="real",
                                      at="2026-11-10T00:00:01+00:00"))
    dataset = tmp_path / "esg_simulated.csv"
    dataset.write_text("x")
    _esg(store, [{"company_id": cid, "transition_grade": "C", **{fid: "7" for fid in FIELD_IDS}} for cid in (REAL, SIM_ONLY)], dataset)
    return store


def test_latest_observation_prefers_the_real_value_and_falls_back_to_the_simulated_one(tmp_path):
    store = _store(tmp_path)
    real = store.latest_observation(REAL, FIELD_SCOPE1, "2026-11-30")
    assert (real.source, real.value) == ("internal_api", 1000.0)
    only = store.latest_observation(SIM_ONLY, FIELD_SCOPE1, "2026-11-30")
    assert (only.source, only.value) == ("simulated", 7.0)
    assert store.latest_observation(REAL, FIELD_SCOPE1, "2026-11-05").source == "simulated"  # before the real load: nothing real yet


def test_the_decision_dataset_shows_the_real_value_and_names_simulated_ones(tmp_path):
    dataset = from_portfolio_snapshot(_store(tmp_path), "2026-11-30", ["fund"], [FIELD_SCOPE1])
    text = dataset.model_dump_json()
    assert '"1000"' in text and '"7"' in text  # REAL keeps its real value; SIM_ONLY has only the simulated one
    assert dataset.name.endswith("(includes simulated ESG values)")


def test_the_decision_dataset_of_real_values_is_named_as_before(tmp_path):
    plain = PortfolioStore(tmp_path / "plain")
    plain.save_portfolio(Portfolio(portfolio_id="fund", name="Fund"))
    plain.save_company(CompanyRef(company_id=REAL, name=REAL))
    plain.save_security(SecurityRef(security_id="s", name="S", company_id=REAL, asset_class="equity", currency="EUR"))
    plain.save_snapshot("fund", "2026-11-30", [Holding(portfolio_id="fund", security_id="s", as_of_date="2026-11-30", quantity=1,
                                                       price=1.0, market_value=1.0, market_value_eur=1.0)])
    plain.append_observation(DataPointObservation(company_id=REAL, field_id=FIELD_SCOPE1, field_name="S1", value=5.0,
                                                  observed_at="2026-11-10T00:00:00+00:00", source="internal_api"))
    assert "simulated" not in from_portfolio_snapshot(plain, "2026-11-30", ["fund"], [FIELD_SCOPE1]).name.lower()


def test_the_stewardship_universe_takes_the_real_value_and_its_note_says_simulated(tmp_path):
    sample = from_portfolio(_store(tmp_path), as_of="2026-11-30")
    fields = {i["issuer_id"]: i["fields"] for i in sample["issuers"]}
    assert fields[REAL][f"portfolio.{FIELD_SCOPE1}"] == 1000.0 and fields[SIM_ONLY][f"portfolio.{FIELD_SCOPE1}"] == 7.0
    assert "Simulated" in sample["note"]


def test_db_import_keeps_the_real_providers_rows_and_makes_no_provider_load_of_simulated_data(tmp_path):
    _store(tmp_path)
    loads = _esg_loads(Settings(portfolios_dir=tmp_path))
    assert [(load["provider"], load["month"]) for load in loads] == [("default", "2026-11")]
    assert loads[0]["rows"] == [{"company_id": REAL, **{fid: 1000.0 for fid in FIELD_IDS}}]


def test_db_import_of_a_store_with_only_simulated_data_has_no_esg_loads(tmp_path):
    _store(tmp_path, real=False)
    assert _esg_loads(Settings(portfolios_dir=tmp_path)) == []
