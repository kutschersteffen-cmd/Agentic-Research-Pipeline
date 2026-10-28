"""Value-chain links and the portfolio overlay on Fixture V (spec 2026-10-27-value-chain-links-overlays-design)."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arp.api.auth import Principal, authorize, current_user
from arp.api.deps import get_portfolio_store, get_taxonomy_store
from arp.api.main import app
from arp.cli import app as cli_app
from arp.llm.base import LLMUsage
from arp.research.indirect_exposure.factory import load_model
from arp.research.value_chain.links import classify_unlinked
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import DataPointObservation, Holding, Portfolio, SecurityRef
from arp.schemas.taxonomy import DerivationMethod, Taxonomy
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.taxonomy_store import TaxonomyStore
from tests.io_tier_fixture import SECTORS, write_fixture_v

BASE = "/api/value-chain"
COPPER, NICKEL = "Mining of copper ores and concentrates", "Mining of nickel ores and concentrates"
MACHINERY = "Manufacture of electrical machinery and apparatus n.e.c."
SX_SPLIT = {"kind": "split", "parts": [{"icio_code": "C27", "share": 0.5}, {"icio_code": "B07", "share": 0.5}]}
NX_NODES = {"kind": "nodes", "parts": [{"region": "WA", "sector": COPPER, "share": 1}]}
runner = CliRunner()


def _store(root) -> tuple[PortfolioStore, TaxonomyStore]:
    """Store S of the spec's Acceptance."""
    store = PortfolioStore(root / "portfolios")
    for cid, country, code in [("cm", "CN", "C27"), ("sx", "CN", "C27"), ("nx", "DE", None), ("us", "US", "C27"), ("dz", "DE", None)]:
        store.save_company(CompanyRef(company_id=cid, name=cid.upper(), country=country, isic_code=code))
    for cid in ("cm", "sx", "nx"):
        store.save_security(SecurityRef(security_id=f"s_{cid}", name=f"Sec {cid}", asset_class="equity", currency="EUR", company_id=cid))
    store.save_security(SecurityRef(security_id="s_cash", name="Cash", asset_class="cash", currency="EUR"))
    store.save_portfolio(Portfolio(portfolio_id="P", name="P"))

    def holdings(date, values):
        return [Holding(holder_id="P", security_id=s, as_of_date=date, market_value=v, market_value_eur=v) for s, v in values.items()]

    store.save_snapshot("P", "2026-09-30", holdings("2026-09-30", {"s_cm": 4e5, "s_sx": 3e5, "s_nx": 2e5, "s_cash": 1e5}))
    store.save_snapshot("P", "2026-06-30", holdings("2026-06-30", {"s_cm": 1e6}))
    for cid, evic, revenue, date in [("cm", 100, 50, "2026-06-01"), ("sx", 60, 30, "2026-09-01")]:
        for field, value in [("climate_evic_eur_m", evic), ("climate_revenue_eur_m", revenue)]:
            store.append_observation(DataPointObservation(
                company_id=cid, field_id=field, field_name=field, value=value, period=date[:7], source="internal_api",
                observed_at=f"{date}T00:00:00Z",
            ))
    taxonomies = TaxonomyStore(root / "taxonomies")
    activity = ActivityDefinition(activity_id="a1", name="Copper and nickel mining", in_scope_description="x",
                                  out_of_scope_description="y", core_isic_codes=["B07"])
    taxonomies._write_new_version(Taxonomy(taxonomy_id="T", name="T", derivation_method=DerivationMethod.MANUAL,
                                           theme=ThemeDefinition(name="T", description="t", activities=[activity])))
    return store, taxonomies


@pytest.fixture
def env(tmp_path, monkeypatch):
    out = tmp_path / "vc"
    res = runner.invoke(cli_app, ["io", "build-full", str(write_fixture_v(tmp_path / "src")), "--out", str(out)])
    assert res.exit_code == 0, res.output
    monkeypatch.setenv("ARP_VALUE_CHAIN_DIR", str(out))
    store, taxonomies = _store(tmp_path)
    app.dependency_overrides[get_portfolio_store] = lambda: store
    app.dependency_overrides[get_taxonomy_store] = lambda: taxonomies
    monkeypatch.setattr("arp.cli._shared._portfolio_store", lambda: store)
    yield TestClient(app), store
    app.dependency_overrides.pop(get_portfolio_store, None)
    app.dependency_overrides.pop(get_taxonomy_store, None)


@pytest.fixture
def linked(env):
    client, store = env
    for cid, body in (("sx", SX_SPLIT), ("nx", NX_NODES)):
        assert client.put(f"{BASE}/links/company/{cid}", json=body).status_code == 200
    return env


def nodes(body):
    return [(n["node_id"], round(n["weight"], 4)) for n in body["nodes"]]


def r4(pairs):
    return [[k, round(v, 4)] for k, v in pairs]


def test_company_links(linked):  # AC-1 to AC-5
    client, _ = linked
    cm = client.get(f"{BASE}/links/company/cm").json()
    assert (cm["source"], cm["region"], nodes(cm), cm["unresolved"], cm["rule"]) == ("code", "CN", [("CN.4", 1.0)], [], None)
    sx = client.get(f"{BASE}/links/company/sx").json()
    assert (sx["source"], nodes(sx), sx["rule"]["kind"]) == ("split", [("CN.4", 0.5), ("CN.1", 0.3571), ("CN.2", 0.1429)], "split")
    assert sx["rule"]["set_by"] and sx["rule"]["set_at"]
    nx = client.get(f"{BASE}/links/company/nx").json()
    assert (nx["source"], nx["region"], nodes(nx)) == ("nodes", "DE", [("WA.1", 1.0)])
    assert (nx["nodes"][0]["sector"], nx["nodes"][0]["region_label"]) == (COPPER, "RoW Asia-Pacific")
    us = client.get(f"{BASE}/links/company/us").json()
    assert (us["source"], us["region"], nodes(us)) == ("code", None, [("CN.4", 0.6154), ("DE.4", 0.3077), ("WA.4", 0.0769)])
    dz = client.get(f"{BASE}/links/company/dz").json()
    assert (dz["source"], dz["region"], dz["nodes"]) == ("none", "DE", [])


def test_code_with_no_node_in_the_region_is_unresolved(env):
    client, store = env
    store.save_company(CompanyRef(company_id="ag", name="AG", country="DE", isic_code="A01"))  # V has no agriculture
    body = client.get(f"{BASE}/links/company/ag").json()
    assert (body["source"], body["nodes"], body["unresolved"]) == ("code", [], [{"icio_code": "A01", "share": 1.0}])


def test_lookup_caches_go_with_their_build(env):
    import gc
    import json
    import os
    import weakref
    from pathlib import Path

    from arp.research.value_chain import links
    from arp.research.value_chain.model import ValueChain

    folder = Path(os.environ["ARP_VALUE_CHAIN_DIR"])
    vc = ValueChain(folder, json.loads((folder / "manifest.json").read_text()))
    assert links.company_region(vc, "CN") == "CN" and len(links._code_nodes(vc)["C27"]) == 3
    gone = weakref.ref(vc)
    del vc
    gc.collect()
    assert gone() is None  # no cache keeps an old build (and its L) alive


def test_split_renormalises_unresolved_parts(env):  # AC-6, AC-7
    client, _ = env
    res = client.put(f"{BASE}/links/company/dz", json={"kind": "split", "parts": [{"icio_code": "A01", "share": 0.4}, {"icio_code": "C27", "share": 0.6}]})
    assert res.status_code == 200
    assert (nodes(res.json()), res.json()["unresolved"]) == ([("DE.4", 1.0)], [{"icio_code": "A01", "share": 0.4}])
    res = client.put(f"{BASE}/links/company/dz", json={"kind": "split", "parts": [{"icio_code": "B07", "share": 0.5}, {"icio_code": "D_GEN_REN", "share": 0.5}]})
    assert nodes(res.json()) == [("DE.1", 0.5), ("DE.3", 0.5)]
    # D and D_GEN_REN both cover wind: those two parts land on one node and add up
    parts = [{"icio_code": "D", "share": 0.25}, {"icio_code": "D_GEN_REN", "share": 0.25}, {"icio_code": "B07", "share": 0.5}]
    res = client.put(f"{BASE}/links/company/dz", json={"kind": "split", "parts": parts})
    assert (nodes(res.json()), res.json()["unresolved"]) == ([("DE.1", 0.5), ("DE.3", 0.5)], [])


@pytest.mark.parametrize(("body", "detail"), [
    ({"kind": "split", "parts": []}, "1 to 20 parts"),
    ({"kind": "split", "parts": [{"icio_code": "C27", "share": 0.5}] * 2}, "duplicate part"),
    ({"kind": "split", "parts": [{"icio_code": "C27", "share": 0}, {"icio_code": "B07", "share": 1}]}, "share must be > 0"),
    ({"kind": "split", "parts": [{"icio_code": "C27", "share": 0.5}, {"icio_code": "B07", "share": 0.4}]}, "shares must sum to 1"),
    ({"kind": "split", "parts": [{"icio_code": "ZZ", "share": 1}]}, "unknown code 'ZZ'"),
    ({"kind": "nodes", "parts": [{"region": "DE", "sector": NICKEL, "share": 1}]}, f"unknown node 'DE · {NICKEL}'"),
    ({"kind": "split", "parts": [{"icio_code": f"C{n}", "share": 1 / 21} for n in range(10, 31)]}, "1 to 20 parts"),
    ({"kind": "split", "parts": [{"icio_code": "C27", "share": True}]}, "each part needs icio_code and a numeric share"),
    ({"kind": "split", "parts": [{"code": "C27", "share": 1}]}, "each part needs icio_code and a numeric share"),
    ({"kind": "nodes", "parts": [{"region": "DE", "share": 1}]}, "each part needs region, sector and a numeric share"),
])
def test_validation(env, body, detail):  # AC-8
    client, store = env
    res = client.put(f"{BASE}/links/company/dz", json=body)
    assert (res.status_code, res.json()["detail"]) == (422, detail)
    assert store.get_link_rule("company:dz") is None


def test_twenty_parts_is_the_limit(env):
    codes = [c["code"] for c in TestClient(app).get(f"{BASE}/codes").json()][:20]
    res = env[0].put(f"{BASE}/links/company/dz", json={"kind": "split", "parts": [{"icio_code": c, "share": 0.05} for c in codes]})
    assert res.status_code == 200 and len(res.json()["rule"]["parts"]) == 20


def test_viewer_cannot_write(linked):  # AC-9, AC-9b
    client, _ = linked
    viewer = Principal(user_id="u_v", name="Vera", role="viewer")
    saved = app.dependency_overrides.pop(authorize)
    app.dependency_overrides[current_user] = lambda: viewer
    try:
        assert client.put(f"{BASE}/links/company/cm", json={"kind": "split", "parts": [{"icio_code": "C27", "share": 1}]}).status_code == 403
        body = client.get(f"{BASE}/links/company/cm").json()
        assert (body["source"], body["rule"]) == ("code", None)
    finally:
        app.dependency_overrides[authorize] = saved


def test_delete_and_unknown(linked):  # AC-10, AC-11
    client, _ = linked
    assert client.delete(f"{BASE}/links/company/sx").status_code == 204
    assert client.delete(f"{BASE}/links/company/sx").status_code == 204
    sx = client.get(f"{BASE}/links/company/sx").json()
    assert (sx["source"], nodes(sx), sx["rule"]) == ("code", [("CN.4", 1.0)], None)
    res = client.get(f"{BASE}/links/company/zz")
    assert (res.status_code, res.json()["detail"]) == (404, "unknown company 'zz'")


def test_node_rule_survives_new_edition(linked, tmp_path, monkeypatch):  # AC-13
    client, _ = linked
    # Fixture V-WA: V without region WA
    monkeypatch.setattr("tests.io_tier_fixture.KEYS", [(r, s) for r in ("DE", "CN") for s in SECTORS])
    monkeypatch.setattr("tests.io_tier_fixture.NODES", [f"{r}.{i}" for r in ("DE", "CN") for i in range(1, 5)])
    monkeypatch.setattr("tests.io_tier_fixture.X", [50, 0, 100, 200, 100, 40, 80, 400])
    out = tmp_path / "vc2"
    res = runner.invoke(cli_app, ["io", "build-full", str(write_fixture_v(tmp_path / "src2", with_y=False)), "--out", str(out)])
    assert res.exit_code == 0, res.output
    monkeypatch.setenv("ARP_VALUE_CHAIN_DIR", str(out))
    nx = client.get(f"{BASE}/links/company/nx").json()
    assert (nx["source"], nx["nodes"], nx["unresolved"]) == ("nodes", [], [{"region": "WA", "sector": COPPER, "share": 1.0}])


def test_activity_links(env):  # AC-14 to AC-16
    client, _ = env
    body = client.get(f"{BASE}/links/activity/T/a1").json()
    assert (body["source"], body["region"]) == ("code", None)
    assert nodes(body) == [("CN.1", 0.3704), ("WA.1", 0.2222), ("DE.1", 0.1852), ("CN.2", 0.1481), ("WA.2", 0.0741)]
    res = client.put(f"{BASE}/links/activity/T/a1", json={"kind": "nodes", "parts": [{"region": "CN", "sector": COPPER, "share": 1}]})
    assert (res.json()["source"], nodes(res.json())) == ("nodes", [("CN.1", 1.0)])
    res = client.put(f"{BASE}/links/activity/T/a1", json={"kind": "split", "parts": [{"icio_code": "ZZ", "share": 2}]})
    assert (res.status_code, res.json()["detail"]) == (422, "split is for companies only")
    assert client.delete(f"{BASE}/links/activity/T/a1").status_code == 204
    assert nodes(client.get(f"{BASE}/links/activity/T/a1").json())[0] == ("CN.1", 0.3704)
    res = client.get(f"{BASE}/links/activity/T/zz")
    assert (res.status_code, res.json()["detail"]) == (404, "unknown activity 'T/zz'")


def test_overlay(linked):  # AC-17 to AC-22, AC-24
    client, _ = linked
    o = client.get(f"{BASE}/portfolio/P", params={"taxonomy": "T", "activity": "a1"}).json()
    assert (o["as_of"], o["nav_eur"], round(o["linked_weight"], 4), round(o["attributed_weight"], 4)) == ("2026-09-30", 1e6, 0.9, 0.7)
    assert [
        (h["security_id"], round(h["weight"], 4), h["link_source"], h["top_node"] and (h["top_node"]["node_id"], h["top_node"]["weight"]),
         h["owned_output_meur"] and round(h["owned_output_meur"], 4))
        for h in o["holdings"]
    ] == [("s_cm", 0.4, "code", ("CN.4", 1.0), 0.2), ("s_sx", 0.3, "split", ("CN.4", 0.5), 0.15),
          ("s_nx", 0.2, "nodes", ("WA.1", 1.0), None), ("s_cash", 0.1, "none", None, None)]
    assert [h["name"] for h in o["holdings"]] == ["Sec cm", "Sec sx", "Sec nx", "Cash"]
    assert nodes(o) == [("CN.4", 0.55), ("WA.1", 0.2), ("CN.1", 0.1071), ("CN.2", 0.0429)]
    assert r4(o["direct_by_region"]) == [["CN", 0.7], ["RoW Asia-Pacific", 0.2]]
    assert round(o["upstream_total"], 4) == 0.2504
    assert r4(o["upstream_by_region"]) == [["CN", 0.1543], ["RoW Asia-Pacific", 0.0592], ["DE", 0.0368]]
    assert r4(o["upstream_by_sector"]) == [[COPPER, 0.099], [MACHINERY, 0.0678], ["Production of electricity by wind", 0.0525], [NICKEL, 0.0311]]
    assert [(n["node_id"], round(n["weight"], 4)) for n in o["upstream_nodes"]] == [
        ("CN.1", 0.0637), ("CN.3", 0.0493), ("WA.1", 0.0336), ("DE.4", 0.032), ("CN.2", 0.0311), ("WA.4", 0.0256)]
    f = o["footprint"]
    assert (f["indicator"], f["unit"], round(f["total"], 4), round(f["per_meur_invested"], 4)) == ("ghg", "t CO₂e", 1.5154, 2.1648)
    assert r4(f["by_region"]) == [["CN", 1.4802], ["DE", 0.0288], ["RoW Asia-Pacific", 0.0064]]
    assert f["per_meur_invested"] == pytest.approx(f["total"] / 0.7, rel=1e-12)  # per M EUR of the attributed 700,000
    assert [h["owned_output_meur"] for h in o["holdings"][:2]] == pytest.approx([0.2, 0.15], rel=1e-12)
    a = o["activity"]
    assert (a["name"], round(a["direct_weight"], 4), round(a["upstream_share"], 4)) == ("Copper and nickel mining", 0.35, 0.5193)
    assert client.get(f"{BASE}/portfolio/P").json()["activity"] is None
    jobs = client.get(f"{BASE}/portfolio/P", params={"indicator": "jobs"}).json()["footprint"]
    assert (jobs["total"], jobs["by_region"]) == (0, [])  # AC-23


@pytest.mark.parametrize(("params", "status", "detail"), [
    ({"taxonomy": "T"}, 422, "taxonomy and activity go together"),
    ({"as_of": "2026-01-01"}, 404, "no holdings for 'P' on or before 2026-01-01"),
    ({"top": 0}, 422, "top must be 1 to 20"),
    ({"top": 21}, 422, "top must be 1 to 20"),
    ({"indicator": "zz"}, 422, "unknown indicator 'zz'"),
])
def test_overlay_errors(linked, params, status, detail):  # AC-25, AC-25b, AC-25f, AC-25i
    res = linked[0].get(f"{BASE}/portfolio/P", params=params)
    assert (res.status_code, res.json()["detail"]) == (status, detail)
    res = linked[0].get(f"{BASE}/portfolio/ZZ")
    assert (res.status_code, res.json()["detail"]) == (404, "unknown portfolio 'ZZ'")


def test_overlay_older_snapshot_and_top(linked):  # AC-25d, AC-25h, AC-25e
    client, _ = linked
    o = client.get(f"{BASE}/portfolio/P", params={"as_of": "2026-06-30"}).json()
    assert (o["nav_eur"], o["linked_weight"], round(o["upstream_total"], 4)) == (1e6, 1, 0.3446)
    assert round(o["footprint"]["per_meur_invested"], 4) == 2.6475
    assert client.get(f"{BASE}/portfolio/P", params={"as_of": "2026-08-15"}).json()["as_of"] == "2026-06-30"
    o = client.get(f"{BASE}/portfolio/P", params={"top": 2}).json()
    assert ([n["node_id"] for n in o["nodes"]], [n["node_id"] for n in o["upstream_nodes"]], len(o["holdings"])) == (
        ["CN.4", "WA.1"], ["CN.1", "CN.3"], 4)
    o = client.get(f"{BASE}/portfolio/P", params={"top": 1}).json()
    assert [len(o[k]) for k in ("direct_by_region", "upstream_by_region", "upstream_by_sector")] == [1, 1, 1]
    assert len(o["footprint"]["by_region"]) == 1


def test_data_points_resolve_as_of_the_snapshot(linked):  # AC-27's rule, on nx
    client, store = linked

    def observe(field, value, date):
        store.append_observation(DataPointObservation(
            company_id="nx", field_id=field, field_name=field, value=value, period=date[:7], source="internal_api",
            observed_at=f"{date}T00:00:00Z"))

    observe("climate_revenue_eur_m", 20, "2026-09-01")
    observe("climate_evic_eur_m", 1, "2026-10-15")  # after the snapshot: nx has no EVIC as of 2026-09-30
    o = client.get(f"{BASE}/portfolio/P").json()
    assert (round(o["attributed_weight"], 4), o["holdings"][2]["owned_output_meur"]) == (0.7, None)
    observe("climate_evic_eur_m", 1, "2026-09-02")
    observe("climate_revenue_eur_m", 99, "2026-10-15")  # later revenue is not seen either
    o = client.get(f"{BASE}/portfolio/P").json()
    assert (round(o["attributed_weight"], 4), o["holdings"][2]["owned_output_meur"]) == (0.9, pytest.approx(0.2 / 1 * 20))


def test_overlay_of_an_unknown_security_with_no_value(env):
    from arp.config import Settings
    from arp.research.value_chain.links import Resolution, company_region, overlay, resolve_activity
    from arp.research.value_chain.model import load_value_chain

    _, store = env
    vc = load_value_chain(Settings().value_chain_dir)
    activity = ActivityDefinition(activity_id="a1", name="A", in_scope_description="x", out_of_scope_description="y",
                                                   core_isic_codes=["B07"])
    ghost = Holding(holder_id="P", security_id="s_ghost", as_of_date="2026-09-30", market_value=0, market_value_eur=0)
    o = overlay(vc, store, [ghost], "2026-09-30", indicator="ghg", top=6,
                activity=("T", activity, resolve_activity(vc, activity, None)))
    assert o["holdings"] == [{"security_id": "s_ghost", "company_id": None, "name": "s_ghost", "market_value_eur": 0,
                              "weight": 0.0, "link_source": "none", "top_node": None, "owned_output_meur": None}]
    assert (o["nav_eur"], o["linked_weight"], o["upstream_total"], o["nodes"], o["direct_by_region"]) == (0, 0, 0, [], [])
    assert (o["footprint"]["per_meur_invested"], o["activity"]["direct_weight"], o["activity"]["upstream_share"]) == (None, 0, None)
    nowhere = activity.model_copy(update={"core_isic_codes": ["ZZ"]})  # codes outside the list are ignored
    assert resolve_activity(vc, nowhere, None) == Resolution("none", None, {}, [])
    assert company_region(vc, None) is None and company_region(vc, "th") == "WA"


def test_overlay_without_rules(env):  # AC-26
    o = env[0].get(f"{BASE}/portfolio/P").json()
    assert round(o["linked_weight"], 4) == 0.7
    assert o["holdings"][2]["link_source"] == "none"


def test_not_built(env, monkeypatch):  # AC-25g
    monkeypatch.delenv("ARP_VALUE_CHAIN_DIR")
    for path in ("/links/company/cm", "/portfolio/P"):
        res = env[0].get(BASE + path)
        assert (res.status_code, res.json()["detail"]) == (503, "value chain not built: run arp io build-full and set ARP_VALUE_CHAIN_DIR")


def test_csv_import(env, tmp_path):  # AC-32
    client, _ = env
    path = tmp_path / "splits.csv"
    path.write_text("company_id,icio_code,share\nsx,C27,0.5\nsx,B07,0.5\ndz,C27,0.7\nzz,C27,1\n")
    res = runner.invoke(cli_app, ["io", "links", "import", str(path)])
    assert res.exit_code == 1
    assert res.stdout == "linked: 1, rejected: 2\n"
    assert res.stderr.splitlines() == ["dz: shares must sum to 1", "zz: unknown company 'zz'"]
    assert client.get(f"{BASE}/links/company/sx").json()["source"] == "split"


class _StubLLM:
    def __init__(self, code):
        self.code, self.calls = code, []

    async def complete_structured(self, *, system, prompt, output_model, **kwargs):
        self.calls.append(prompt)
        return output_model(isic_code=self.code, rationale="stub"), LLMUsage()


@pytest.mark.parametrize(("args", "detail"), [
    (["--portfolio", "ZZ"], "unknown portfolio 'ZZ'"),
    (["--portfolio", "P", "--as-of", "2026-01-01"], "no holdings for 'P' on or before 2026-01-01"),
])
def test_classify_command_refuses_what_it_cannot_read(env, args, detail):
    res = runner.invoke(cli_app, ["io", "links", "classify", *args])
    assert (res.exit_code, res.stderr.strip()) == (1, detail)


def test_classify_unlinked(env, monkeypatch):  # AC-33, AC-34, AC-34b, AC-35
    import os

    client, store = env
    model = load_model(os.environ["ARP_VALUE_CHAIN_DIR"])
    none = _StubLLM(None)
    assert asyncio.run(classify_unlinked(store, "P", "2026-09-30", model, none)) == (0, 1)
    assert client.get(f"{BASE}/links/company/nx").json()["rule"] is None
    llm = _StubLLM("C27")
    assert asyncio.run(classify_unlinked(store, "P", "2026-09-30", model, llm)) == (1, 0)
    assert len(llm.calls) == 1 and "Company: NX" in llm.calls[0]
    nx = client.get(f"{BASE}/links/company/nx").json()
    assert (nx["source"], nodes(nx), nx["rule"]["set_by"]) == ("llm", [("DE.4", 1.0)], "llm")
    client.put(f"{BASE}/links/company/nx", json=NX_NODES)
    again = _StubLLM("C27")
    assert asyncio.run(classify_unlinked(store, "P", "2026-09-30", model, again)) == (0, 0) and again.calls == []

    # a second portfolio Q holds two unlinked companies; classifying P never reaches them
    store.save_company(CompanyRef(company_id="zx", name="ZX", country="DE"))
    for cid in ("dz", "zx"):
        store.save_security(SecurityRef(security_id=f"s_{cid}", name=cid, asset_class="equity", currency="EUR", company_id=cid))
    store.save_portfolio(Portfolio(portfolio_id="Q", name="Q"))
    store.save_snapshot("Q", "2026-09-30", [Holding(holder_id="Q", security_id=s, as_of_date="2026-09-30", market_value=1, market_value_eur=1)
                                            for s in ("s_dz", "s_zx")])
    assert asyncio.run(classify_unlinked(store, "P", "2026-09-30", model, _StubLLM(None))) == (0, 0)
    assert asyncio.run(classify_unlinked(store, "Q", "2026-09-30", model, _StubLLM(None))) == (0, 2)
    assert asyncio.run(classify_unlinked(store, "Q", "2026-09-30", model, _StubLLM("C27"))) == (2, 0)

    store.save_company(CompanyRef(company_id="cm", name="CM", country="CN"))
    assert asyncio.run(classify_unlinked(store, "P", "2026-09-30", model, _StubLLM("B07"))) == (1, 0)
    store.save_company(CompanyRef(company_id="cm", name="CM", country="CN", isic_code="C27"))
    cm = client.get(f"{BASE}/links/company/cm").json()
    assert (cm["source"], nodes(cm), cm["rule"]["kind"]) == ("code", [("CN.4", 1.0)], "llm")


def test_esg_template_has_revenue_after_evic(env):  # AC-36
    header = env[0].get("/api/portfolio/esg/template").text.splitlines()[0].split(",")
    assert header[header.index("climate_evic_eur_m") + 1] == "climate_revenue_eur_m"


def test_codes_lists_the_split_codes_last():
    codes = TestClient(app).get(f"{BASE}/codes").json()
    assert len(codes) == 55 and [c["code"] for c in codes[-5:]] == ["D_GEN_FOS", "D_GEN_NUC", "D_GEN_REN", "D_TD", "D_GAS"]


# --- Scope 8: the shocks' portfolio lens ---------------------------------------


def test_shock_lens(linked):  # AC-28 to AC-31b
    client, _ = linked
    demand = {"model": "demand", "region": "CN", "change": -10}
    q = client.get(f"{BASE}/shock/quantity", params={**demand, "portfolio": "P"}).json()
    lens = q["portfolio"]
    assert (lens["portfolio_id"], lens["as_of"], round(lens["linked_weight"], 4), round(lens["change_pct"], 4)) == (
        "P", "2026-09-30", 0.9, -8.2277)
    assert round(q["total_meur"], 4) == -64.2658
    supply = client.get(f"{BASE}/shock/quantity", params={**demand, "model": "supply", "portfolio": "P"}).json()
    assert round(supply["portfolio"]["change_pct"], 4) == -7.1757
    price = client.get(f"{BASE}/shock/price", params={"carbon_eur_per_t": 100, "portfolio": "P"}).json()
    assert round(price["portfolio"]["dp_pct"], 4) == 0.0347 and set(price["portfolio"]) == {"portfolio_id", "as_of", "linked_weight", "dp_pct"}

    plain = client.get(f"{BASE}/shock/quantity", params=demand).json()
    assert plain["portfolio"] is None and {k: v for k, v in q.items() if k != "portfolio"} == {k: v for k, v in plain.items() if k != "portfolio"}
    for path, params in (("quantity", demand), ("price", {"carbon_eur_per_t": 100})):
        res = client.get(f"{BASE}/shock/{path}", params={**params, "as_of": "2026-09-30"})
        assert (res.status_code, res.json()["detail"]) == (422, "as_of needs portfolio")


def test_shock_lens_snapshot_and_errors(linked):
    client, _ = linked
    demand = {"model": "demand", "region": "CN", "change": -10}
    older = client.get(f"{BASE}/shock/quantity", params={**demand, "portfolio": "P", "as_of": "2026-08-15"}).json()
    assert (older["portfolio"]["as_of"], older["portfolio"]["linked_weight"]) == ("2026-06-30", 1.0)  # only s_cm, on CN.4
    for params, detail in (({"portfolio": "ZZ"}, "unknown portfolio 'ZZ'"),
                           ({"portfolio": "P", "as_of": "2026-01-01"}, "no holdings for 'P' on or before 2026-01-01")):
        res = client.get(f"{BASE}/shock/price", params={"carbon_eur_per_t": 100, **params})
        assert (res.status_code, res.json()["detail"]) == (404, detail)


def test_shock_lens_with_nothing_linked(env):
    client, store = env
    store.save_snapshot("P", "2026-10-01", [Holding(holder_id="P", security_id="s_cash", as_of_date="2026-10-01",
                                                    market_value=1, market_value_eur=1)])
    lens = client.get(f"{BASE}/shock/price", params={"carbon_eur_per_t": 100, "portfolio": "P"}).json()["portfolio"]
    assert (lens["as_of"], lens["linked_weight"], lens["dp_pct"]) == ("2026-10-01", 0.0, None)


def test_openapi_has_the_lens_parameters():  # AC-37b
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    for path in ("/api/value-chain/shock/quantity", "/api/value-chain/shock/price"):
        assert {"portfolio", "as_of"} <= {p["name"] for p in paths[path]["get"]["parameters"]}
