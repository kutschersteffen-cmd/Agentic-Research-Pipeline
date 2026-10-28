"""Revenue routes on fixture F: docs/superpowers/specs/2026-10-27-value-chain-revenue-routes-design.md, Acceptance."""

import numpy as np
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arp.api.auth import Principal, authorize, current_user
from arp.api.main import app
from arp.cli import app as cli_app
from arp.research.value_chain import revenue
from arp.research.value_chain.model import load_value_chain
from arp.schemas.value_chain import RecipeIn
from tests import value_chain_fixture as fx

BASE = "/api/value-chain"
CAVEAT = (
    "EXIOBASE 3.11.2 · 2022 · basic prices, M EUR · now-cast years are estimates · capital goods not included in flows"
)
M = (
    "Revenue shares assume every node sells to its buyers in the table's proportions; a recipe replaces its home "
    "node's purchases only for the recipe's output."
)
OBA, COPPER, RICE = "Other business activities", "Mining of copper ores and concentrates", "Cultivation of paddy rice"
R = {
    "name": "Test battery", "home": {"region": "DE", "sector": OBA}, "output_meur": 50,
    "inputs": [{"region": "DE", "sector": COPPER, "share": 0.2}, {"region": "CN", "sector": OBA, "share": 0.1}],
    "source": "test",
}


def _build(root, monkeypatch, **patch):
    with monkeypatch.context() as m:
        for name, value in patch.items():
            m.setattr(fx, name, value)
        root.mkdir()
        res = CliRunner().invoke(cli_app, ["io", "build-full", str(fx.write_fixture_f(root)), "--out", str(root / "out")])
    assert res.exit_code == 0, res.output
    return root / "out"


@pytest.fixture(scope="module")
def builds(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    root = tmp_path_factory.mktemp("rr")
    z2 = [row[:] for row in fx.Z]
    z2[3][1] = 0  # F2: CN.3 sells nothing to DE.3
    keys3 = [(r, s) for r in fx.REGIONS for s in (RICE, "Other business activities (74)", COPPER)]
    z4 = [[0 if 3 in (i, j) else v for j, v in enumerate(row)] for i, row in enumerate(fx.Z)]
    sat4 = {f: {k: v[:3] + [0] for k, v in rows.items()} for f, rows in fx.SATELLITES.items()}
    out = {
        "F": _build(root / "f", mp),
        "F2": _build(root / "f2", mp, Z=z2),
        "F3": _build(root / "f3", mp, KEYS=keys3, LIVE=[keys3[2], keys3[1], keys3[5], keys3[4]]),
        "F4": _build(root / "f4", mp, Z=z4, X=[100, 200, 100, 0], SATELLITES=sat4),
    }
    mp.undo()
    return out


@pytest.fixture
def env(builds, tmp_path, monkeypatch):
    monkeypatch.setenv("ARP_VALUE_CHAIN_DIR", str(builds["F"]))
    monkeypatch.setenv("ARP_VALUE_CHAIN_RECIPES_DIR", str(tmp_path / "recipes"))
    return TestClient(app), lambda name: monkeypatch.setenv("ARP_VALUE_CHAIN_DIR", str(builds[name]))


@pytest.fixture
def client(env):
    return env[0]


def get(client, path, code=200):
    res = client.get(BASE + path)
    assert res.status_code == code, res.text
    return res.json()


def post(client, body, code=201):
    res = client.post(f"{BASE}/recipes", json=body)
    assert res.status_code == code, res.text
    return res.json()


def r4(x):
    return round(x, 4)


def rows(items, *keys):
    return [(i["node_id"], *(r4(i[k]) for k in keys)) for i in items]


def routes(body):
    return [(r["nodes"], r4(r["share"])) for r in body["routes"]]


def test_node_exposure(client):  # AC-1, AC-2
    body = get(client, "/exposure?target=DE.3")
    assert (body["basis"], body["target_label"], body["caveat"], body["model_caveat"]) == ("node", "Other business activities · DE", CAVEAT, M)
    assert (body["recipe_source"], body["unlisted_share"], body["target"]) == (None, None, "DE.3")
    assert rows(body["items"], "share", "direct", "revenue_meur") == [
        ("DE.2", 0.2473, 0.2, 24.7261), ("CN.3", 0.2254, 0.2, 22.5352), ("DE.3", 0.1138, 0.1, 22.7543), ("CN.2", 0.0282, 0, 2.8169),
    ]
    assert [i["node_id"] for i in get(client, "/exposure?target=DE.3&top=2")["items"]] == ["DE.2", "CN.3"]


def test_node_routes(client):  # AC-3, AC-4, AC-5
    body = get(client, "/routes?target=DE.3&from=CN.3")
    assert (r4(body["share"]), body["from"], body["target"]) == (0.2254, "CN.3", "DE.3")
    assert routes(body) == [
        (["CN.3", "DE.3"], 0.2), (["CN.3", "CN.3", "DE.3"], 0.02), (["CN.3", "CN.2", "CN.3", "DE.3"], 0.002),
        (["CN.3", "CN.3", "CN.3", "DE.3"], 0.002),
    ]
    assert (r4(body["shown_share"]), r4(body["rest_share"])) == (0.224, 0.0014)
    top3 = get(client, "/routes?target=DE.3&from=CN.3&top=3")
    assert routes(top3) == routes(body)[:3] and r4(top3["rest_share"]) == 0.0034
    short = get(client, "/routes?target=DE.3&from=CN.3&max_hops=2&min_share=0.01")
    assert routes(short) == [(["CN.3", "DE.3"], 0.2), (["CN.3", "CN.3", "DE.3"], 0.02)]


def test_recipe_save_and_exposure(client):  # AC-6, AC-7, AC-8, AC-9, AC-22b
    saved = post(client, R)
    rid = saved["recipe_id"]
    got = get(client, f"/recipes/{rid}")
    assert got == saved
    assert (got["name"], r4(got["unlisted_share"]), got["status"], got["set_by"]) == ("Test battery", 0.7, "ok", "Test")
    assert got["inputs"] == R["inputs"] and got["model_caveat"] == M and got["edition"] == "exiobase-IOT_2022_ixi"
    body = get(client, f"/exposure?target=recipe:{rid}")
    assert (body["basis"], body["target_label"], body["recipe_source"], r4(body["unlisted_share"])) == ("recipe", "Test battery", "test", 0.7)
    assert rows(body["items"], "share", "direct", "revenue_meur") == [
        ("DE.2", 0.1183, 0.1, 11.8276), ("CN.3", 0.0575, 0.05, 5.7516), ("CN.2", 0.0072, 0, 0.719), ("DE.3", 0.007, 0, 1.3941),
    ]
    t = f"recipe:{rid}"
    de2 = get(client, f"/routes?target={t}&from=DE.2&min_share=0.002")
    assert r4(de2["share"]) == 0.1183 and r4(de2["rest_share"]) == 0.0033
    assert routes(de2) == [(["DE.2", t], 0.1), (["DE.2", "DE.2", t], 0.01), (["DE.2", "CN.3", t], 0.005)]
    de3 = get(client, f"/routes?target={t}&from=DE.3&min_share=0.002")
    assert r4(de3["share"]) == 0.007 and routes(de3) == [(["DE.3", "DE.2", t], 0.005)]
    for path in ("/routes?target=DE.3&from=CN.3", "/recipes", f"/recipes/{rid}"):
        b = get(client, path)
        assert (b["edition"], b["caveat"], b["model_caveat"]) == ("exiobase-IOT_2022_ixi", CAVEAT, M)
    listed = get(client, "/recipes")["items"]
    assert listed == [{"recipe_id": rid, "name": "Test battery", "home": R["home"], "output_meur": 50, "n_inputs": 2, "status": "ok"}]


def _with(**change):
    return {**R, **change}


@pytest.mark.parametrize(("body", "detail"), [
    (_with(inputs=[R["inputs"][0], {"region": "CN", "sector": COPPER, "share": 0.1}]),
     "the recipe buys more from Mining of copper ores and concentrates · CN than Other business activities · DE does in total"),
    (_with(output_meur=200), "output_meur must be below the home node's output (200 M EUR)"),
    (_with(output_meur=0), "output_meur must be below the home node's output (200 M EUR)"),
    (_with(inputs=[{**R["inputs"][0], "share": 0.6}, {**R["inputs"][1], "share": 0.5}]), "input shares add up to more than 1"),
    (_with(inputs=[*R["inputs"], {"region": "DE", "sector": RICE, "share": 0.1}]), "no output: DE · Cultivation of paddy rice"),
    (_with(home={"region": "XX", "sector": OBA}), "unknown node XX · Other business activities"),
    (_with(inputs=[R["inputs"][0], {**R["inputs"][0], "share": 0.1}]), "input named twice: DE · Mining of copper ores and concentrates"),
    (_with(inputs=[]), "a recipe has 1 to 50 inputs"),
    (_with(inputs=[R["inputs"][0], {**R["inputs"][1], "share": 0}]), "input share must be above 0: CN · Other business activities"),
])
def test_save_checks(client, body, detail):  # AC-10 to AC-15c
    assert post(client, body, 422)["detail"] == detail
    assert get(client, "/recipes")["items"] == []


def test_body_shape_is_the_framework_422(client):
    assert isinstance(post(client, _with(name=""), 422)["detail"], list)
    assert isinstance(post(client, {k: v for k, v in R.items() if k != "source"}, 422)["detail"], list)


def test_viewer_cannot_write(client):  # AC-16, AC-16b
    saved = app.dependency_overrides.pop(authorize)
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u_v", name="Vera", role="viewer")
    try:
        assert client.post(f"{BASE}/recipes", json=R).status_code == 403
        assert get(client, "/recipes")["items"] == []
    finally:
        app.dependency_overrides[authorize] = saved


def test_later_builds(env):  # AC-17 to AC-17e
    client, switch = env
    rid = post(client, R)["recipe_id"]
    switch("F2")
    detail = "the recipe buys more from Other business activities · CN than Other business activities · DE does in total"
    assert get(client, f"/exposure?target=recipe:{rid}", 409)["detail"] == detail
    assert get(client, f"/routes?target=recipe:{rid}&from=DE.2", 409)["detail"] == detail
    assert get(client, "/recipes")["items"][0]["status"] == "inconsistent"
    switch("F3")
    assert get(client, f"/recipes/{rid}")["status"] == "ok"
    assert rows(get(client, f"/exposure?target=recipe:{rid}")["items"], "share") == [
        ("DE.3", 0.1183), ("CN.2", 0.0575), ("CN.3", 0.0072), ("DE.2", 0.007),
    ]
    switch("F4")
    assert get(client, f"/exposure?target=recipe:{rid}", 409)["detail"] == "no output: CN · Other business activities"
    assert get(client, "/recipes")["items"][0]["status"] == "unresolved"
    assert get(client, f"/recipes/{rid}")["status"] == "unresolved"


def test_update_and_delete(client):  # AC-19, AC-19b, AC-20
    rid = post(client, R)["recipe_id"]
    res = client.put(f"{BASE}/recipes/{rid}", json=_with(output_meur=100))
    assert res.status_code == 200 and res.json()["output_meur"] == 100
    items = get(client, f"/exposure?target=recipe:{rid}")["items"]
    assert [i["node_id"] for i in items] == ["DE.2", "CN.3", "CN.2", "DE.3"]
    assert rows(items[:2], "direct", "share") == [("DE.2", 0.2, 0.2349), ("CN.3", 0.1, 0.1142)]
    assert client.delete(f"{BASE}/recipes/{rid}").status_code == 204
    assert get(client, f"/exposure?target=recipe:{rid}", 404)["detail"] == f"unknown recipe '{rid}'"
    assert client.delete(f"{BASE}/recipes/{rid}").status_code == 404
    assert client.put(f"{BASE}/recipes/{rid}", json=R).status_code == 404
    assert post(client, R)["recipe_id"] != rid
    assert get(client, "/recipes/..secret", 404)["detail"] == "unknown recipe '..secret'"


def test_restart_keeps_recipes(client):  # AC-18: a new store on the same directory is what a restarted process reads
    saved = post(client, R)
    assert get(TestClient(app), f"/recipes/{saved['recipe_id']}") == saved


def test_unknown_and_out_of_range(client):  # AC-21, AC-22
    for path in ("/exposure?target=DE.1", "/routes?target=DE.3&from=DE.1"):
        assert get(client, path, 404)["detail"] == "unknown node 'DE.1'"
    for path in (
        "/exposure?target=DE.3&top=101", "/routes?target=DE.3&from=CN.3&max_hops=7",
        "/routes?target=DE.3&from=CN.3&min_share=0.00001", "/routes?target=DE.3&from=CN.3&top=51", "/exposure",
    ):
        get(client, path, 422)


def test_not_built(client, monkeypatch):  # AC-23
    monkeypatch.delenv("ARP_VALUE_CHAIN_DIR")
    not_built = {"detail": "value chain not built: run arp io build-full and set ARP_VALUE_CHAIN_DIR"}
    assert get(client, "/exposure?target=DE.3", 503) == not_built
    assert post(client, R, 503) == not_built
    for res in (client.get(f"{BASE}/recipes"), client.delete(f"{BASE}/recipes/{'0' * 32}")):
        assert (res.status_code, res.json()) == (503, not_built)


def test_closed_forms_match_a_solve(builds):  # the rank-one updates agree with (I - B')⁻¹ d to 1e-9
    vc = load_value_chain(builds["F"])
    x, a = vc._x, vc._a
    b = np.divide(a * x, x[:, None], out=np.zeros_like(a), where=vc._live[:, None])
    for node_id in ("DE.2", "DE.3", "CN.2", "CN.3"):
        t = revenue.node_target(vc, node_id)
        bp = b.copy()
        bp[:, t.col] = 0
        assert np.allclose(np.linalg.solve(np.eye(len(x)) - bp, t.d), t.r, atol=1e-9)
    recipe = revenue.recipe_target(vc, "recipe:x", revenue.check(vc, RecipeIn(**R)))
    bp = b.copy()
    bp[:, recipe.col] -= recipe.d
    assert np.allclose(np.linalg.solve(np.eye(len(x)) - bp, recipe.d), recipe.r, atol=1e-9)


def test_routes_add_up(client):  # AC-26 on F: all routes of up to 6 hops cover the share, less what is cut
    for target in ("DE.2", "DE.3", "CN.2", "CN.3"):
        for seller in get(client, f"/exposure?target={target}&top=100")["items"]:
            body = get(client, f"/routes?target={target}&from={seller['node_id']}&max_hops=6&min_share=0.0001&top=50")
            assert abs(body["shown_share"] - sum(r["share"] for r in body["routes"])) < 1e-12
            assert body["rest_share"] >= -1e-9 and abs(body["share"] - seller["share"]) < 1e-9
