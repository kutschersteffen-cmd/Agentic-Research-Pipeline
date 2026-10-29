"""AC-1..AC-7b: the "All source values" dataset over company_facts and the portfolio store."""

from __future__ import annotations

import os

import pytest

from tests.authoritative_fixtures import PICKS, add_fact, ensure_field, row, seed
from tests.authoritative_fixtures import build as _build

DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set")


@pytest.fixture(autouse=True)
def _db():
    from arp.storage.postgres import ensure_schema
    from tests.postgres_helpers import reset_postgres_tables

    ensure_schema(DSN)
    reset_postgres_tables(DSN)
    yield
    reset_postgres_tables(DSN)


@pytest.fixture
def fixture():
    return seed(DSN)


def build(fx, **kwargs):
    return _build(DSN, fx, **kwargs)


def test_ac_1_a_row_cells(fixture):
    ds = build(fixture)
    assert ds.source == "source_values"
    assert ds.as_of == "2026-10-15"
    assert len(ds.rows) == 2
    a = row(ds, fixture["A"])
    assert a["prov_esg_demo_scope1"] == "100"
    assert a["prov_esg_demo_scope1__period_end"] == "2026-09-30"
    assert a["prov_esg_demo_scope1__source"] == "provider"
    assert a["prov_esg_demo_scope1__provider"] == "esg_demo"
    assert a["scope1_tco2e"] == "90"
    assert a["scope1_tco2e__status"] == "approved"
    assert a["scope1_tco2e__source"] == "extraction"
    assert a["scope1_tco2e__provider"] == ""
    assert a["scope1_tco2e__observation_id"] == str(fixture["a_ext"])


def test_ac_2_b_has_no_extracted_value(fixture):
    b = row(build(fixture), fixture["B"])
    assert b["scope1_tco2e"] == ""
    assert b["scope1_tco2e__status"] == ""


def test_ac_3_latest_period_wins(fixture):
    from arp.db.session import transaction

    with transaction(DSN) as s:
        add_fact(s, fixture["A"], "scope1_tco2e", 80, "2024-12-31", valid_from="2026-03-01")
    a = row(build(fixture), fixture["A"])
    assert a["scope1_tco2e"] == "90"
    assert a["scope1_tco2e__period_end"] == "2025-12-31"


def test_ac_4_empty_basis_wins_tie(fixture):
    from arp.db.session import transaction

    with transaction(DSN) as s:
        add_fact(s, fixture["A"], "scope1_tco2e", 85, "2025-12-31", valid_from="2026-03-01", basis="restated")
    assert row(build(fixture), fixture["A"])["scope1_tco2e"] == "90"


def test_ac_5_as_of_hides_later_facts(fixture):
    ds = build(fixture, as_of="2026-09-01")
    assert row(ds, fixture["A"])["prov_esg_demo_scope1"] == ""
    assert row(ds, fixture["B"])["prov_esg_demo_scope1"] == ""
    assert row(ds, fixture["A"])["scope1_tco2e"] == "90"


def test_ac_6_alias_collision_names_both_fields(fixture):
    with pytest.raises(ValueError) as exc:
        build(fixture, picks=[{"field_id": "scope1_tco2e"}, {"field_id": "prov:esg_demo:scope1", "alias": "scope1_tco2e"}])
    assert "scope1_tco2e" in str(exc.value) and "prov:esg_demo:scope1" in str(exc.value)


def _portfolio(tmp_path, observations):
    from arp.schemas.portfolio import DataPointObservation
    from arp.storage.portfolio_store import PortfolioStore

    store = PortfolioStore(tmp_path)
    for company, value, source in observations:
        store.append_observation(DataPointObservation(
            company_id=company, field_id="climate_scope1_tco2e", field_name="Scope 1", value=value, unit="tCO2e",
            period="FY2025", observed_at="2026-05-01T00:00:00+00:00", source=source,
        ))
    return store


def test_ac_7_portfolio_input(fixture, tmp_path):
    store = _portfolio(tmp_path, [("U-A", 200, "internal_api")])
    picks = [{"field_id": "climate_scope1_tco2e", "portfolio_source": "internal_api"}]
    a = row(build(fixture, picks=picks, portfolio_store=store), fixture["A"])
    assert a["portfolio_internal_api_climate_scope1_tco2e"] == "200"
    assert a["portfolio_internal_api_climate_scope1_tco2e__period"] == "FY2025"
    assert a["portfolio_internal_api_climate_scope1_tco2e__source"] == "internal_api"


def test_ac_7b_other_source_is_not_used(fixture, tmp_path):
    store = _portfolio(tmp_path, [("U-A", 200, "internal_api"), ("U-B", 300, "catalogue")])
    picks = [{"field_id": "climate_scope1_tco2e", "portfolio_source": "internal_api"}]
    b = row(build(fixture, picks=picks, portfolio_store=store), fixture["B"])
    assert b["portfolio_internal_api_climate_scope1_tco2e"] == ""


def test_unknown_company_is_skipped(fixture):
    ds = build(fixture, company_ids=[fixture["A"], "00000000-0000-0000-0000-000000000000"])
    assert [r["company_id"] for r in ds.rows] == [fixture["A"]]
    assert "1 unknown" in ds.source_ref


def test_unknown_field_is_refused(fixture):
    with pytest.raises(ValueError, match="no_such_field"):
        build(fixture, picks=[{"field_id": "no_such_field"}])


def test_text_value_passes_through(fixture):
    from arp.db.session import transaction

    with transaction(DSN) as s:
        ensure_field(s, "target_text", data_type="text")
        add_fact(s, fixture["A"], "target_text", "Net zero 2050", "2025-12-31", valid_from="2026-03-01", unit=None)
    a = row(build(fixture, picks=[{"field_id": "target_text"}]), fixture["A"])
    assert a["target_text"] == "Net zero 2050"


def test_route_builds_dataset_and_refuses_collision_with_422(pg, fixture, tmp_path):  # pg first: it empties the tables
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from arp.api.auth import current_user
    from arp.api.deps import get_decision_store, get_portfolio_store, get_run_store
    from arp.api.routers import decision as decision_router
    from arp.storage.decision_store import DecisionStore
    from tests.conftest import PRINCIPAL

    app = FastAPI()
    app.include_router(decision_router.router)
    app.dependency_overrides[get_decision_store] = lambda: DecisionStore(tmp_path / "fw")
    app.dependency_overrides[get_run_store] = lambda: None
    app.dependency_overrides[get_portfolio_store] = lambda: None
    app.dependency_overrides[current_user] = lambda: PRINCIPAL
    body = {"source": "source_values", "company_ids": [fixture["A"], fixture["B"]], "picks": PICKS, "as_of": "2026-10-15"}
    with TestClient(app) as c:
        ok = c.post("/api/decision/datasets/from-source", json=body)
        assert ok.status_code == 200, ok.text
        assert ok.json()["row_count"] == 2
        bad = c.post("/api/decision/datasets/from-source",
                     json={**body, "picks": [{"field_id": "scope1_tco2e"}, {"field_id": "scope1_tco2e"}]})
        assert bad.status_code == 422
        assert "scope1_tco2e" in bad.json()["detail"]


def test_review_duplicate_company_ids_give_one_row(fixture):
    ds = build(fixture, company_ids=[fixture["A"], fixture["A"], fixture["B"]])
    assert sorted(r["company_id"] for r in ds.rows) == sorted([fixture["A"], fixture["B"]])


@pytest.mark.parametrize("alias", ["company_id", "Company", "a:b", "x__unit", "Scope", "1st"])
def test_review_bad_alias_is_refused(fixture, alias):
    with pytest.raises(ValueError, match="column name"):
        build(fixture, picks=[{"field_id": "scope1_tco2e", "alias": alias}])
