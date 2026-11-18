"""Showcase defect 8 (backend): Holdings Intake lists portfolios that have no holder record without storing one,
names a missing column by its file header, and takes the decimal separator and the weight unit per upload."""
import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_identifier_map, get_portfolio_store, get_run_store
from arp.api.main import app
from arp.holdings.intake import previous_month_end
from arp.portfolio.mock_data import generate_demo_dataset
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.run_store import RunStore

ISIN = "US0378331005"
HEADER = "ISIN,LEI,Name,Weight (%),Quantity,Price,Market value,Currency,FX rate to EUR"


@pytest.fixture
def env(tmp_path, pg):
    store = PortfolioStore(tmp_path / "pf")
    app.dependency_overrides[get_portfolio_store] = lambda: store
    app.dependency_overrides[get_identifier_map] = lambda: IdentifierMapStore(tmp_path / "idmap.jsonl")
    app.dependency_overrides[get_run_store] = lambda: RunStore(pg, tmp_path / "runs")
    yield TestClient(app), store
    for dep in (get_portfolio_store, get_identifier_map, get_run_store):
        app.dependency_overrides.pop(dep, None)


def _upload(client, holder_id, body: str, **fields):
    return client.post("/api/holdings/upload", files={"file": ("h.csv", body.encode(), "text/csv")},
                       data={"holder_id": holder_id, "kind": "portfolio", "as_of": "2026-10-30", **fields})


def _row(weight="100", market_value="1000", sep=","):
    return sep.join([ISIN, "", "Apple", weight, "", "", market_value, "EUR", ""])


def test_holders_lists_seeded_portfolios_without_storing_a_holder(env):  # AC-114, AC-116
    client, store = env
    asyncio.run(generate_demo_dataset(store, today=date.today()))
    rows = client.get("/api/holdings/holders").json()["holders"]
    assert sorted(r["holder_id"] for r in rows) == sorted(p.portfolio_id for p in store.list_portfolios()) and len(rows) == 4
    assert store.list_holders() == []
    row = next(r for r in rows if r["holder_id"] == "sustainable_leaders")
    latest = store.latest_snapshot_date("sustainable_leaders")
    assert row == {
        "holder_id": "sustainable_leaders", "kind": "portfolio", "name": "Sustainable Leaders Fund", "source": None,
        "as_of": latest, "last_pull_at": None, "last_error": None, "expected_as_of": previous_month_end(date.today()),
        "stale": latest < previous_month_end(date.today()), "age_days": (date.today() - date.fromisoformat(latest)).days}
    assert client.get("/api/security-master/unmatched").json()["rows"] == []
    assert [i for i in client.get("/api/issues").json()["issues"] if i["source"] == "security_master"] == []


def test_a_configured_holder_is_listed_once_with_its_source(env):
    client, store = env
    assert _upload(client, "fund_a", f"{HEADER}\n{_row()}\n").status_code == 200
    rows = [r for r in client.get("/api/holdings/holders").json()["holders"] if r["holder_id"] == "fund_a"]
    assert len(rows) == 1 and rows[0]["source"] == "file"


def test_a_missing_column_is_named_by_its_file_header(env):
    client, _store = env
    header = HEADER.replace(",Weight (%)", "").replace(",Currency", "")
    r = _upload(client, "cols", f"{header}\n{ISIN},,Apple,,,1000,\n")
    assert r.status_code == 422
    assert [e for e in r.json()["detail"]["errors"] if e["row"] is None] == [
        {"row": None, "column": "Weight (%)", "message": "missing required column"},
        {"row": None, "column": "Currency", "message": "missing required column"}]


def test_decimal_comma_is_read_when_the_upload_says_so(env):  # AC-126
    client, store = env
    body = f"{HEADER.replace(',', ';')}\n{_row('100,0', '1000,50', sep=';')}\n"
    assert _upload(client, "comma2", body).status_code == 422  # the default is a decimal point, as before
    r = _upload(client, "comma", body, decimal=",")
    assert (r.status_code, r.json()["status"]) == (200, "written")
    [holding] = store.load_snapshot("comma", "2026-10-30")
    assert (holding.market_value, holding.weight_pct) == (1000.5, 100)


def test_weights_as_fractions_are_read_when_the_upload_says_so(env):  # AC-129
    client, store = env
    body = f"{HEADER}\n{_row(weight='1')}\n"
    r = _upload(client, "frac2", body)
    assert r.status_code == 422 and r.json()["detail"]["errors"][0]["message"].startswith("weights sum to 1%")
    r = _upload(client, "frac", body, weight_unit="fraction")
    assert (r.status_code, r.json()["status"]) == (200, "written")
    assert store.load_snapshot("frac", "2026-10-30")[0].weight_pct == 100


def test_any_other_decimal_or_weight_unit_is_refused(env):
    client, _store = env
    body = f"{HEADER}\n{_row()}\n"
    assert _upload(client, "opts", body, decimal=";").status_code == 422
    assert _upload(client, "opts", body, weight_unit="bps").status_code == 422
    assert [r for r in client.get("/api/holdings/holders").json()["holders"] if r["holder_id"] == "opts"] == []
