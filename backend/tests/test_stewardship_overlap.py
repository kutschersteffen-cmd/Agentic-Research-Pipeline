"""Spec stewardship-workbench-overlap, PR 1 (backend): the overlap maths on unit fixture U, the shared selections, the
time budget, and the two routes on the sample universe (fixture W) and on two small funds."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, Portfolio, SecurityRef
from arp.stewardship import overlap, worklist

Q = worklist.cycle_of(datetime.now(UTC).date())


class MemoryStore:
    """The few portfolio-store reads `fund_holdings()` makes, over one snapshot date."""

    def __init__(self, funds: dict[str, list[tuple[str, str | None, float]]]) -> None:
        self.portfolios = [Portfolio(portfolio_id=pid, name=f"Fund {pid}") for pid in funds]
        self.securities, self.holdings = {}, []
        for pid, held in funds.items():
            for sid, cid, value in held:
                self.securities[sid] = SecurityRef(
                    security_id=sid, name=sid, asset_class="equity", currency="EUR", company_id=cid
                )
                self.holdings.append(Holding(holder_id=pid, security_id=sid, as_of_date="2026-11-02", market_value_eur=value))

    def all_snapshot_dates(self):
        return ["2026-11-02"]

    def list_portfolios(self):
        return self.portfolios

    def list_securities(self):
        return list(self.securities.values())

    def list_resolutions(self):
        return {}

    def load_holdings_as_of(self, as_of):
        return self.holdings


def fixture_u() -> dict[str, dict]:
    store = MemoryStore({
        "A": [("x", "x", 600), ("y", "y", 400)],
        "B": [("x", "x", 200), ("y", "y", 300), ("z", "z", 500)],
        "C": [("z", "z", 100), ("unresolved", None, 900)],
    })  # fmt: skip
    return worklist.fund_holdings(store)


def _pair(result: dict, a: str, b: str) -> tuple[int, float]:
    p = next(p for p in result["pairs"] if {p["a"], p["b"]} == {a, b})
    return p["shared_companies"], p["shared_weight_pct"]


def test_pairs_on_fixture_u():
    # AC-1, AC-2, AC-35
    result = overlap.overview(fixture_u(), {}, {})
    assert _pair(result, "A", "B") == (2, 50.0)
    assert _pair(result, "B", "C") == (1, 50.0)
    assert _pair(result, "A", "C") == (0, 0.0)
    assert [(p["a"], p["b"]) for p in result["pairs"]] == [("A", "B"), ("A", "C"), ("B", "C")]
    assert result["companies"] == 3
    assert [(f["portfolio_id"], f["companies"]) for f in result["funds"]] == [("A", 2), ("B", 3), ("C", 1)]


def test_top_matrix_on_fixture_u():
    # AC-3
    grid = overlap.matrix(fixture_u(), {}, n=2)
    assert [c["issuer_id"] for c in grid["companies"]] == ["x", "y"]
    x = grid["companies"][0]
    assert (x["house_weight_pct"], grid["companies"][1]["house_weight_pct"]) == (38.095, 33.333)
    assert (x["weights"], x["funds"]) == ({"A": 60.0, "B": 20.0, "C": None}, 2)


def test_selection_matrix_puts_a_company_no_fund_holds_last():
    grid = overlap.matrix(fixture_u(), {"y": "Ypsilon"}, picked={"q": "Quux", "y": "y-log", "x": "Ex"})
    assert [(c["issuer_id"], c["company"], c["house_weight_pct"], c["funds"]) for c in grid["companies"]] == [
        ("x", "Ex", 38.095, 2), ("y", "Ypsilon", 33.333, 2), ("q", "Quux", None, 0)
    ]  # fmt: skip
    assert grid["companies"][2]["weights"] == {"A": None, "B": None, "C": None}


def test_shared_selection_of_a_deleted_group():
    # AC-45
    rows = {"house": {"x": {"issuer_id": "x", "company": "X", "status": "confirmed"}},
            "group:gone": {"x": {"issuer_id": "x", "company": "X", "status": "proposed"}},
            "group:solo": {"y": {"issuer_id": "y", "company": "Y", "status": "proposed"}}}  # fmt: skip
    result = overlap.overview(fixture_u(), rows, {})
    assert result["shared_selections"] == [{
        "issuer_id": "x", "company": "X",
        "scopes": [{"scope": "house", "label": "All house holdings", "status": "confirmed"},
                   {"scope": "group:gone", "label": "group:gone", "status": "proposed"}],
        "held_in": [{"portfolio_id": "A", "name": "Fund A", "weight_pct": 60.0}, {"portfolio_id": "B", "name": "Fund B", "weight_pct": 20.0}],
    }]  # fmt: skip


def test_shared_selections_order():
    def picked(*iids):
        return {i: {"issuer_id": i, "company": i.upper(), "status": "proposed"} for i in iids}

    rows = {"group:b": picked("m", "a"), "portfolio:z": picked("m", "a", "k"), "house": picked("m", "k")}
    result = overlap.overview({}, rows, {"group:b": "beta", "portfolio:z": "Alpha"})
    assert [(e["issuer_id"], [s["scope"] for s in e["scopes"]]) for e in result["shared_selections"]] == [
        ("m", ["house", "portfolio:z", "group:b"]), ("a", ["portfolio:z", "group:b"]), ("k", ["house", "portfolio:z"])
    ]  # fmt: skip


def _best_of_three(fn) -> float:
    times = []
    for _ in range(3):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    return min(times)  # one wall-clock reading fails on a busy CI machine


def test_time_budget():
    # AC-25: 7 funds, fund i holding the first 300 + i x 383 companies at EUR 1 m each (the largest holds 2,598)
    store = MemoryStore({f"F{i}": [(f"c{k}", f"c{k}", 1e6) for k in range(300 + i * 383)] for i in range(7)})
    assert _best_of_three(lambda: overlap.overview(worklist.fund_holdings(store), {}, {})) < 1.0
    assert _best_of_three(lambda: overlap.matrix(worklist.fund_holdings(store), {}, n=100)) < 1.0


# --- the routes (Postgres) ---


@pytest.fixture
def client(sample_house_universe, pg, monkeypatch, tmp_path):
    pytest.importorskip("zen")
    from arp.api.deps import get_portfolio_store, get_stream_store
    from arp.api.main import app
    from arp.config import get_settings
    from arp.stewardship.process import StreamStore

    monkeypatch.setenv("ARP_ENGAGEMENTS_DIR", str(tmp_path / "engagements"))
    monkeypatch.setenv("ARP_ENGAGEMENT_STORE", "postgres")
    monkeypatch.setenv("ARP_PORTFOLIOS_DIR", str(tmp_path / "portfolios"))
    get_settings.cache_clear()
    get_portfolio_store.cache_clear()
    root = get_settings().stewardship_streams_dir
    app.dependency_overrides[get_stream_store] = lambda: StreamStore(root)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_stream_store, None)
    get_portfolio_store.cache_clear()


def _select(client, scope: str, *ids: str) -> None:
    r = client.post("/api/stewardship/selection", json={"cycle": Q, "scope": scope, "add": list(ids)})
    assert r.status_code == 200, r.text


def _files(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted((root / "selection").rglob("*")) if p.is_file()}


def test_sample_universe(client):
    # AC-18, AC-39, AC-43, AC-44, AC-19, AC-20, AC-21, AC-22
    from arp.config import get_settings

    g = client.post(
        "/api/portfolio/groups", json={"group_id": "g", "name": "g", "kind": "companies", "members": ["SYN01", "SYN02"]}
    )
    assert g.status_code == 200, g.text
    _select(client, "house", "SYN01", "SYN02")
    _select(client, "group:g", "SYN01")
    r = client.get("/api/stewardship/overlap")
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["as_of"], body["cycle"], body["funds"], body["pairs"], body["companies"]) == (None, Q, [], [], 0)
    [entry] = body["shared_selections"]
    assert (entry["issuer_id"], entry["held_in"]) == ("SYN01", [])
    assert entry["scopes"] == [{"scope": "house", "label": "All house holdings", "status": "proposed"},
                               {"scope": "group:g", "label": "g", "status": "proposed"}]  # fmt: skip
    top = client.get("/api/stewardship/overlap/matrix").json()
    assert (top["funds"], top["companies"], top["as_of"], top["basis"], top["scope"], top["cycle"]) == (
        [],
        [],
        None,
        "top",
        None,
        Q,
    )
    sel = client.get("/api/stewardship/overlap/matrix", params={"basis": "selection", "scope": "house"}).json()
    assert {c["issuer_id"] for c in sel["companies"]} == {"SYN01", "SYN02"}
    assert all((c["house_weight_pct"], c["funds"], c["weights"]) == (None, 0, {}) for c in sel["companies"])
    assert (sel["basis"], sel["scope"]) == ("selection", "house")
    root = get_settings().stewardship_streams_dir
    before = _files(root)
    assert client.post("/api/stewardship/selection/confirm", json={"cycle": Q, "scope": "house"}).status_code == 200
    scopes = client.get("/api/stewardship/overlap").json()["shared_selections"][0]["scopes"]
    assert [s["status"] for s in scopes] == ["confirmed", "proposed"]
    assert _files(root) != before
    before = _files(root)
    client.get("/api/stewardship/overlap")
    client.get("/api/stewardship/overlap/matrix", params={"basis": "selection", "scope": "group:g"})
    assert _files(root) == before  # AC-24: reads write nothing
    old = client.get("/api/stewardship/overlap", params={"cycle": "2020-Q1"})
    assert (old.status_code, old.json()["cycle"], old.json()["shared_selections"]) == (200, "2020-Q1", [])
    bad = client.get("/api/stewardship/overlap", params={"cycle": "2026-13"})
    assert (bad.status_code, bad.json()["detail"]) == (422, f"A cycle looks like {Q}")
    # a fund scope needs the portfolio universe, as on the worklist
    r = client.get("/api/stewardship/overlap/matrix", params={"basis": "selection", "scope": "portfolio:p"})
    assert (r.status_code, r.json()["detail"]) == (422, "Fund scopes need the portfolio universe")


def test_matrix_validation(client):
    # AC-13, AC-16, AC-17
    def detail(**params):
        r = client.get("/api/stewardship/overlap/matrix", params=params)
        return r.status_code, r.json()["detail"]

    assert detail(n=201) == (422, "n must be 1 to 200")
    assert detail(n=0) == (422, "n must be 1 to 200")
    assert detail(basis="selection") == (422, "basis selection needs a scope")
    assert detail(basis="nope") == (422, "Unknown basis nope")
    assert detail(cycle="2026-13", basis="top") == (422, f"A cycle looks like {Q}")
    assert client.get("/api/stewardship/overlap/matrix", params={"basis": "selection", "scope": "group:nope"}).status_code == 404
    assert (
        client.get("/api/stewardship/overlap/matrix", params={"basis": "selection", "scope": "house", "n": 500}).status_code
        == 200
    )


@pytest.fixture
def funds(client):
    """P1 holds A for 60 m and B for 40 m; P2 holds B for 100 m; P3 holds only a security with no company."""
    from arp.config import get_settings
    from arp.stewardship.universe import HouseUniverseSetting
    from arp.storage.portfolio_store_factory import build_portfolio_store

    settings = get_settings()
    store = build_portfolio_store(settings)
    for cid in ("A", "B"):
        store.save_company(CompanyRef(company_id=cid, name=f"Company {cid}", sector="Energy"))
        store.save_security(SecurityRef(security_id=f"{cid}-EQ", name=cid, asset_class="equity", currency="EUR", company_id=cid))
    store.save_security(SecurityRef(security_id="N-EQ", name="N", asset_class="equity", currency="EUR"))
    for pid, name, held in (
        ("P1", "zeta", (("A-EQ", 60e6), ("B-EQ", 40e6))),
        ("P2", "Alpha", (("B-EQ", 100e6),)),
        ("P3", "m", (("N-EQ", 5e6),)),
    ):
        store.save_portfolio(Portfolio(portfolio_id=pid, name=name))
        store.save_snapshot(
            pid,
            "2026-11-02",
            [Holding(holder_id=pid, security_id=s, as_of_date="2026-11-02", market_value_eur=v) for s, v in held],
        )
    HouseUniverseSetting(settings.stewardship_streams_dir).set("portfolio", "tests")
    return store


def test_routes_on_two_funds(client, funds):
    # AC-4..AC-12, AC-15, AC-23 on two small funds
    body = client.get("/api/stewardship/overlap").json()
    assert (body["as_of"], body["companies"]) == ("2026-11-02", 2)
    assert body["funds"] == [
        {"portfolio_id": "P2", "name": "Alpha", "companies": 1},
        {"portfolio_id": "P1", "name": "zeta", "companies": 2},
    ]
    scopes = {s["key"]: s["companies"] for s in client.get("/api/stewardship/worklist/scopes").json()["scopes"]}
    assert {f"portfolio:{f['portfolio_id']}": f["companies"] for f in body["funds"]} == {
        k: v for k, v in scopes.items() if k.startswith("portfolio:")
    }
    assert body["pairs"] == [{"a": "P2", "b": "P1", "shared_companies": 1, "shared_weight_pct": 40.0}]
    top = client.get("/api/stewardship/overlap/matrix").json()
    house = {r["issuer_id"]: r for r in client.get("/api/stewardship/worklist", params={"scope": "house"}).json()["rows"]}
    assert [c["issuer_id"] for c in top["companies"]] == ["B", "A"]
    for c in top["companies"]:
        row = house[c["issuer_id"]]
        assert c["house_weight_pct"] == pytest.approx(row["holdings_weight_pct"], abs=0.001)
        held = {h["portfolio_id"]: h["weight_pct"] for h in row["held_in"]}
        assert c["weights"] == {pid: held.get(pid) for pid in ("P2", "P1")}
        assert c["funds"] == len(held)
    assert top["companies"][1]["company"] == "Company A"
    assert [c["issuer_id"] for c in client.get("/api/stewardship/overlap/matrix", params={"n": 1}).json()["companies"]] == ["B"]
    _select(client, "portfolio:P1", "A")
    _select(client, "house", "A")
    sel = client.get("/api/stewardship/overlap/matrix", params={"basis": "selection", "scope": "portfolio:P1"}).json()
    assert ([c["issuer_id"] for c in sel["companies"]], sel["scope"]) == (["A"], "portfolio:P1")
    [entry] = client.get("/api/stewardship/overlap").json()["shared_selections"]
    assert entry["scopes"] == [{"scope": "house", "label": "All house holdings", "status": "proposed"},
                               {"scope": "portfolio:P1", "label": "zeta", "status": "proposed"}]  # fmt: skip
    assert entry["held_in"] == [{"portfolio_id": "P1", "name": "zeta", "weight_pct": 60.0}]
    assert (
        client.get("/api/stewardship/overlap/matrix", params={"basis": "selection", "scope": "portfolio:nope"}).status_code == 404
    )
