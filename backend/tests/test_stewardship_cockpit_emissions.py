"""Spec `stewardship-cockpit` PR 2: per-company financed emissions and the cockpit's `emissions` section."""

# ruff: noqa: F811 -- the `client` fixture is imported from the PR 1 suite and taken as a test argument

from __future__ import annotations

import pytest

pytest.importorskip("zen")

from arp.config import get_settings  # noqa: E402
from arp.portfolio.climate import metrics  # noqa: E402
from arp.portfolio.climate.schemas import FIELD_EVIC, FIELD_SCOPE1, FIELD_SCOPE2  # noqa: E402
from arp.schemas.common import CompanyRef  # noqa: E402
from arp.schemas.portfolio import DataPointObservation, Holding, Portfolio, SecurityRef  # noqa: E402
from arp.stewardship.cockpit import emissions_of  # noqa: E402
from arp.stewardship.tiers import TIERS  # noqa: E402
from arp.storage.portfolio_store import portfolio_directories  # noqa: E402
from arp.storage.portfolio_store_factory import build_portfolio_store  # noqa: E402
from tests.test_stewardship_cockpit import AS_OF, _confirm, _engagement, _get, client  # noqa: E402, F401

A, B, C = "isin_XA0000000001", "isin_XB0000000002", "isin_XC0000000003"


def _portfolio_p():
    """AC-53: A 1m EUR (EVIC 100, S1 800, S2 200), B 2m EUR (EVIC 100, S1 300, S2 200), C 1m EUR without EVIC."""
    store = build_portfolio_store(get_settings())
    store.save_portfolio(Portfolio(portfolio_id="P", name="Fund P"))
    holdings = []
    for cid, name, sector, mv in ((A, "Alpha AG", "Utilities", 1e6), (B, "Beta SE", "Materials", 2e6), (C, "Gamma NV", "Energy", 1e6)):
        isin = cid.removeprefix("isin_")
        store.save_company(CompanyRef(company_id=cid, name=name, sector=sector))
        store.save_security(SecurityRef(security_id=isin, isin=isin, name=name, asset_class="equity", currency="EUR", company_id=cid))
        holdings.append(Holding(holder_id="P", security_id=isin, as_of_date="2026-11-01", market_value_eur=mv))
    store.save_snapshot("P", "2026-11-01", holdings)
    for cid, values in ((A, {FIELD_EVIC: 100.0, FIELD_SCOPE1: 800.0, FIELD_SCOPE2: 200.0}), (B, {FIELD_EVIC: 100.0, FIELD_SCOPE1: 300.0, FIELD_SCOPE2: 200.0}),
                        (C, {FIELD_SCOPE1: 50.0, FIELD_SCOPE2: 50.0})):  # fmt: skip
        for field, value in values.items():
            store.append_observation(DataPointObservation(company_id=cid, field_id=field, field_name=field, value=value, source="internal_api", observed_at="2026-11-01"))
    return store


def test_buckets_and_contributors_ac53_ac54(client, pg):
    _portfolio_p()
    _engagement(client, pg, company_id=A, name="Alpha AG")
    _confirm(B, TIERS[0])
    e = _get(client, portfolio_id="P")["emissions"]
    assert {k: v for k, v in e.items() if k != "contributors"} == {
        "total_tco2e": 20.0, "engaged_tco2e": 10.0, "selected_not_engaged_tco2e": 10.0, "not_selected_tco2e": 0.0, "uncovered_holding_count": 1,
    }  # fmt: skip
    assert e["contributors"] == [
        {"company_id": A, "company": "Alpha AG", "sector": "Utilities", "tco2e": 10.0, "share": 0.5, "status": "engaged"},
        {"company_id": B, "company": "Beta SE", "sector": "Materials", "tco2e": 10.0, "share": 0.5, "status": "selected"},
    ]


def test_escalated_contributor_ac88(client, pg):
    _portfolio_p()
    eid = _engagement(client, pg, company_id=A, name="Alpha AG")
    assert client.post(f"/api/engagement/records/{A}/issues/{eid}/escalate", json={"stage": "written_escalation_to_board"}).status_code == 200
    contributors = _get(client, portfolio_id="P")["emissions"]["contributors"]
    assert [(c["company_id"], c["status"]) for c in contributors] == [(A, "in_escalation"), (B, "not_selected")]


def test_climate_module_unchanged_and_per_company_sums_to_it_ac56(client):
    store = _portfolio_p()
    securities, _ = portfolio_directories(store)
    holdings = store.load_holdings_as_of(AS_OF, ["P"])
    assert metrics.compute_financed_emissions(store, holdings, securities, as_of=AS_OF, portfolio_filter=["P"]) == {
        "as_of": AS_OF, "financed_emissions_tco2e": 20.0, "covered_market_value_eur": 3000000.0, "uncovered_market_value_eur": 1000000.0,
        "coverage_pct": 0.75, "uncovered_holding_count": 1,
    }  # fmt: skip
    assert metrics.financed_emissions_by_company(store, holdings, securities, as_of=AS_OF) == ({A: 10.0, B: 10.0}, 1)


def test_all_portfolios_scope_matches_climate_module_ac57(client, pg):
    store = _portfolio_p()
    securities, _ = portfolio_directories(store)
    expected = metrics.compute_financed_emissions(store, store.load_holdings_as_of(AS_OF, None), securities, as_of=AS_OF)
    assert _get(client)["emissions"]["total_tco2e"] == pytest.approx(expected["financed_emissions_tco2e"], abs=0.1)


def test_null_without_holdings_ac59(client, pg):
    _portfolio_p()
    build_portfolio_store(get_settings()).save_portfolio(Portfolio(portfolio_id="Q", name="Empty"))
    assert _get(client, portfolio_id="Q")["emissions"] is None
    assert _get(client, as_of="2026-10-31")["emissions"] is None  # no snapshot on or before


def test_emissions_of_top_six_ties_and_buckets_ac58():
    financed = {f"c{i}": float(v) for i, v in enumerate([5, 5, 9, 1, 2, 3, 4, 0.333])}
    companies = {c: CompanyRef(company_id=c, name=n) for c, n in (("c0", "Zed"), ("c1", "Abe"))}
    e = emissions_of(financed, 2, companies, engaged={"c2", "c3"}, selected={"c3", "c4"}, escalated={"c2"})
    assert [c["company_id"] for c in e["contributors"]] == ["c2", "c1", "c0", "c6", "c5", "c4"]
    assert e["contributors"][0] == {"company_id": "c2", "company": "c2", "sector": None, "tco2e": 9.0, "share": round(9 / 29.333, 4), "status": "in_escalation"}
    assert e["engaged_tco2e"] + e["selected_not_engaged_tco2e"] + e["not_selected_tco2e"] == pytest.approx(e["total_tco2e"], abs=0.1)
    assert (e["engaged_tco2e"], e["selected_not_engaged_tco2e"], e["uncovered_holding_count"]) == (10.0, 2.0, 2)
    assert emissions_of({}, 3, {}, set(), set(), set()) is None
