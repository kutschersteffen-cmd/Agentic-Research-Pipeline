from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.auth import Principal, current_user
from arp.api.routers import portfolio
from arp.config import Settings
from arp.portfolio import aggregation
from arp.portfolio.aggregation import aggregate
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, PortfolioGroup, SecurityRef
from arp.storage.portfolio_store import PortfolioStore
from tests.postgres_helpers import reset_postgres_tables

DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")

# A made-up fixture: not real GICS data (that is licensed and never shipped).
REFERENCE_CSV = "code,label,level\n10,Fixture Energy,sector\n1010,Fixture Energy Group,industry_group\n"
COMPANY_CSV = "company_id,gics_code\nacme,10101010\nglobex,10102020\n"


def _group(group_id="grp_a", members=("b", "a", "b"), kind="portfolios") -> PortfolioGroup:
    return PortfolioGroup(
        group_id=group_id, name="G", kind=kind, members=list(members), created_at="2026-10-04T00:00:00Z", created_by="Ann"
    )


def test_group_reload_returns_same_set(tmp_path):
    store = PortfolioStore(tmp_path)
    store.save_group(_group(members=["p2", "p1"]))
    reloaded = PortfolioStore(tmp_path).get_group("grp_a")
    assert reloaded is not None and reloaded.members == ["p1", "p2"]
    assert [g.group_id for g in store.list_groups()] == ["grp_a"]


def test_group_saved_resolved_and_sorted(tmp_path):
    store = PortfolioStore(tmp_path)
    store.save_group(_group(members=["b", "a", "b"]))
    assert store.get_group("grp_a").members == ["a", "b"]
    store.save_group(_group(members=["z"]))  # same id: a new version, latest wins
    assert store.get_group("grp_a").members == ["z"]
    assert len(store.list_groups()) == 1
    assert store.get_group("missing") is None


def _gics_world():
    securities = {
        "s1": SecurityRef(security_id="s1", isin=None, name="s1", asset_class="equity", currency="EUR", company_id="acme"),
        "s2": SecurityRef(security_id="s2", isin=None, name="s2", asset_class="equity", currency="EUR", company_id="globex"),
        "s3": SecurityRef(security_id="s3", isin=None, name="s3", asset_class="equity", currency="EUR", company_id="initech"),
    }
    companies = {c: CompanyRef(company_id=c, name=c) for c in ("acme", "globex", "initech")}
    holdings = [
        Holding(portfolio_id="p", security_id=s, as_of_date="2026-01-01", quantity=1, price=v, market_value=v,
                market_value_eur=v)
        for s, v in (("s1", 10.0), ("s2", 5.0), ("s3", 1.0))
    ]
    return holdings, securities, companies


def _settings(monkeypatch, **kw):
    aggregation._gics_tables.cache_clear()
    monkeypatch.setattr(aggregation, "get_settings", lambda: Settings(**kw))


def test_aggregate_by_gics_sector_with_fixture(tmp_path, monkeypatch):
    ref, co = tmp_path / "ref.csv", tmp_path / "co.csv"
    ref.write_text(REFERENCE_CSV)
    co.write_text(COMPANY_CSV)
    _settings(monkeypatch, gics_reference_path=ref, company_gics_path=co)
    holdings, securities, companies = _gics_world()
    res = aggregate(holdings, securities, companies, group_by="gics_sector", metric="market_value_sum", as_of="2026-01-01")
    assert {r.group_value: r.market_value_eur for r in res.rows} == {"Fixture Energy": 15.0, "(unresolved)": 1.0}
    res = aggregate(holdings, securities, companies, group_by="gics_industry_group", metric="market_value_sum", as_of="2026-01-01")
    assert {r.group_value: r.market_value_eur for r in res.rows} == {"Fixture Energy Group": 15.0, "(unresolved)": 1.0}
    # a level with no label in the reference file has no value
    res = aggregate(holdings, securities, companies, group_by="gics_industry", metric="market_value_sum", as_of="2026-01-01")
    assert {r.group_value for r in res.rows} == {"(unresolved)"}


def test_gics_missing_files_gives_none(tmp_path, monkeypatch):
    _settings(monkeypatch)
    holdings, securities, companies = _gics_world()
    for dim in ("gics_sector", "gics_industry_group", "gics_industry", "gics_sub_industry"):
        assert aggregation._dimension_value(holdings[0], securities, companies, dim) is None
    _settings(monkeypatch, gics_reference_path=tmp_path / "nope.csv", company_gics_path=tmp_path / "nope2.csv")
    assert aggregation._dimension_value(holdings[0], securities, companies, "gics_sector") is None


@pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set -- opt-in Postgres backend")
def test_pg_store_parity_pg(tmp_path):
    from arp.storage.postgres import ensure_schema
    from arp.storage.postgres_portfolio_store import PostgresPortfolioStore

    ensure_schema(DSN)
    reset_postgres_tables(DSN)
    pg = PostgresPortfolioStore(DSN, PortfolioStore(tmp_path / "pg-files"))
    file_store = PortfolioStore(tmp_path / "files")
    for store in (pg, file_store):
        store.save_group(_group(members=["b", "a"]))
        store.save_group(_group(members=["c", "a"]))
        store.save_group(_group("grp_b", members=["x"], kind="companies"))
    assert pg.get_group("grp_a") == file_store.get_group("grp_a")
    assert sorted(g.group_id for g in pg.list_groups()) == sorted(g.group_id for g in file_store.list_groups())
    assert pg.get_group("nope") is None


def _client(tmp_path, principal) -> TestClient:
    app = FastAPI()
    app.include_router(portfolio.router)
    store = PortfolioStore(tmp_path)
    app.dependency_overrides[deps.get_portfolio_store] = lambda: store
    app.dependency_overrides[current_user] = lambda: principal
    return TestClient(app)


def test_group_api_hides_user_id(tmp_path):
    analyst = Principal(user_id="u-secret-1", name="Ann Analyst", role="analyst")
    client = _client(tmp_path, analyst)
    r = client.post("/api/portfolio/groups", json={"name": "Core", "kind": "portfolios", "members": ["p2", "p1", "p2"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created_by"] == "Ann Analyst" and body["members"] == ["p1", "p2"]
    assert body["group_id"].startswith("grp_")
    assert "u-secret-1" not in r.text
    assert client.get(f"/api/portfolio/groups/{body['group_id']}").json() == body
    assert client.get("/api/portfolio/groups").json() == [body]
    assert client.get("/api/portfolio/groups/nope").status_code == 404

    viewer = _client(tmp_path, Principal(user_id="u-2", name="Vic", role="viewer"))
    assert viewer.get("/api/portfolio/groups").status_code == 200
    assert viewer.post("/api/portfolio/groups", json={"name": "x", "kind": "portfolios", "members": []}).status_code == 403
