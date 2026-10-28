"""Shock endpoints on fixture F; spec docs/superpowers/specs/2026-10-26-value-chain-shocks-design.md."""

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arp.api.main import app
from arp.api.routers.value_chain import MODEL_CAVEATS
from arp.cli import app as cli_app
from tests.value_chain_fixture import Z, write_fixture_f

Q = "/api/value-chain/shock/quantity"
P = "/api/value-chain/shock/price"
NOT_BUILT = "value chain not built: run arp io build-full and set ARP_VALUE_CHAIN_DIR"
CAVEAT = (
    "EXIOBASE 3.11.2 · 2022 · basic prices, M EUR · now-cast years are estimates · capital goods not included in flows"
)
MINING = "Mining of copper ores and concentrates"
OBA = "Other business activities"


def _build(root, z=Z):
    res = CliRunner().invoke(cli_app, ["io", "build-full", str(write_fixture_f(root, z=z)), "--out", str(root / "out")])
    assert res.exit_code == 0, res.output
    return root / "out"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return _build(tmp_path_factory.mktemp("vc"))


@pytest.fixture(scope="module")
def built_f2(tmp_path_factory):  # F2: CN.3's Z row [0, 40, 10, 60], so y of CN.3 = -10
    return _build(tmp_path_factory.mktemp("vc2"), [*Z[:3], [0, 40, 10, 60]])


# AC-23 / AC-23b: no key, and a key that would fail every model call; the shocks must not care.
@pytest.fixture(params=[None, "sk-invalid"], ids=["no-key", "invalid-key"], autouse=True)
def api_key(request, monkeypatch):
    if request.param is None:
        monkeypatch.delenv("ARP_ANTHROPIC_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ARP_ANTHROPIC_API_KEY", request.param)


@pytest.fixture
def client(built, monkeypatch):
    monkeypatch.setenv("ARP_VALUE_CHAIN_DIR", str(built))
    return TestClient(app)


@pytest.fixture
def client_f2(built_f2, monkeypatch):
    monkeypatch.setenv("ARP_VALUE_CHAIN_DIR", str(built_f2))
    return TestClient(app)


def get(client, path, **params):
    res = client.get(path, params=params or None)
    assert res.status_code == 200, res.text
    return res.json()


def r4(x):
    return round(x, 4)


def pairs(items):
    return [[k, r4(v)] for k, v in items]


def shocked(body):
    return [(s["node_id"], r4(s["base_meur"]), r4(s["shock_meur"])) for s in body["shocked"]]


def test_demand_region(client):  # AC-1 to AC-4, AC-11
    body = get(client, Q, model="demand", region="DE", change=-10, unit="pct")
    assert body["change_pct"] == -10 and body["skipped"] == []
    assert shocked(body) == [("DE.2", 60, -6), ("DE.3", 160, -16)]
    assert r4(body["total_meur"]) == -30.1819
    assert pairs(body["by_region"]) == [["DE", -27.798], ["CN", -2.3839]]
    assert pairs(body["by_sector"]) == [[OBA, -20.9253], [MINING, -9.2566]]
    assert [(n["node_id"], r4(n["delta_meur"])) for n in body["nodes"]] == [
        ("DE.3", -18.8063), ("DE.2", -8.9917), ("CN.3", -2.119), ("CN.2", -0.2649),
    ]
    assert {k: r4(v) for k, v in body["indicators"].items()} == {"ghg": -45.7955, "energy": -0.8992, "jobs": -299.1701}
    assert (body["model_caveat"], body["edition"], body["caveat"]) == (
        MODEL_CAVEATS["demand"], "exiobase-IOT_2022_ixi", CAVEAT,
    )
    assert body["focus"] is None


def test_demand_meur(client):  # AC-5, AC-6
    body = get(client, Q, model="demand", region="DE", change=-22, unit="meur")
    assert (r4(body["change_pct"]), r4(body["total_meur"])) == (-10, -30.1819)
    body = get(client, Q, model="demand", node="DE.3", change=-2, unit="meur")
    assert r4(body["total_meur"]) == -2.8218
    assert (r4(body["indicators"]["ghg"]), r4(body["indicators"]["jobs"])) == (-1.4955, -27.9004)


def test_demand_sector_and_union(client):  # AC-7, AC-8
    body = get(client, Q, model="demand", sector=OBA, change=-10, unit="pct")
    assert [s["node_id"] for s in body["shocked"]] == ["CN.3", "DE.3"]
    assert r4(body["total_meur"]) == -31.1566
    assert pairs(body["by_region"]) == [["DE", -21.2396], ["CN", -9.917]]
    body = get(client, Q, model="demand", node="DE.3", region="DE", change=-10, unit="pct")
    assert [s["node_id"] for s in body["shocked"]] == ["DE.2", "DE.3"]
    assert r4(body["total_meur"]) == -30.1819


def test_supply(client):  # AC-9, AC-10, AC-11
    body = get(client, Q, model="supply", node="DE.2", change=-10, unit="pct")
    assert shocked(body) == [("DE.2", 80, -8)]
    assert r4(body["total_meur"]) == -12.5446
    assert [(n["node_id"], r4(n["delta_meur"])) for n in body["nodes"]] == [
        ("DE.2", -9.0129), ("DE.3", -2.232), ("CN.3", -1.0313), ("CN.2", -0.2684),
    ]
    assert body["model_caveat"] == MODEL_CAVEATS["supply"]
    body = get(client, Q, model="supply", node="CN.2", change=-10, unit="pct")
    assert pairs(body["by_region"]) == [["CN", -8.4655], ["DE", -0.2013]]
    assert r4(body["indicators"]["jobs"]) == -10.4891


def test_focus_top_and_defaults(client):  # AC-12, AC-13, AC-23c
    body = get(client, Q, model="demand", node="DE.3", change=-10, unit="pct", focus="CN.3")
    assert (body["focus"]["node_id"], r4(body["focus"]["delta_meur"])) == ("CN.3", -2.0343)
    body = get(client, Q, model="demand", region="DE", change=-10, unit="pct", top=1)
    assert [r for r, _ in body["by_region"]] == ["DE"] and [s for s, _ in body["by_sector"]] == [OBA]
    assert [n["node_id"] for n in body["nodes"]] == ["DE.3"]
    assert get(client, Q, model="demand", node="DE.2", change=-10)["change_pct"] == -10


def test_price_all(client):  # AC-11, AC-15, AC-16
    body = get(client, P, carbon_eur_per_t=100)
    assert body["covered_regions"] == ["CN", "DE"]
    assert (r4(body["priced_t"]), r4(body["carbon_cost_meur"])) == (627, 0.0627)
    assert [(n["node_id"], r4(n["dp_pct"])) for n in body["nodes"]] == [
        ("DE.2", 0.0564), ("CN.2", 0.0148), ("CN.3", 0.0109), ("DE.3", 0.0075),
    ]
    assert pairs(body["by_region"]) == [["DE", 0.0238], ["CN", 0.0129]]
    assert pairs(body["by_sector"]) == [[MINING, 0.0356], [OBA, 0.0086]]
    assert (body["model_caveat"], body["caveat"]) == (MODEL_CAVEATS["price"], CAVEAT)


def test_price_region_and_zero(client):  # AC-17, AC-18
    body = get(client, P, carbon_eur_per_t=100, region="DE", focus="CN.2")
    assert body["covered_regions"] == ["DE"]
    assert (r4(body["priced_t"]), r4(body["carbon_cost_meur"])) == (500, 0.05)
    assert pairs(body["by_region"]) == [["DE", 0.0234], ["CN", 0.0041]]
    assert r4(body["focus"]["dp_pct"]) == 0.0017
    body = get(client, P, carbon_eur_per_t=0)
    assert (body["priced_t"], body["carbon_cost_meur"]) == (627, 0)
    assert body["nodes"] == body["by_region"] == body["by_sector"] == []


def test_model_caveats_exact():  # AC-11, Definitions
    assert MODEL_CAVEATS == {
        "demand": "Linear Leontief model: fixed input recipes, no substitution, no capacity limits, no price effects.",
        "supply": "Ghosh dependency indicator, not a forecast: downstream output resting on the lost inputs if every "
        "buyer keeps its sales shares; no substitution or rerouting.",
        "price": "Leontief cost-push: full pass-through of the carbon cost, no substitution, no demand response; "
        "producers' direct emissions only, households' own emissions not priced; basic prices.",
    }


@pytest.mark.parametrize(
    ("path", "detail"),
    [
        (Q + "?model=demand&change=-10&unit=pct", None),
        (Q + "?model=demand&node=DE.1&change=-10", "unknown node 'DE.1'"),
        (Q + "?model=demand&region=FR&change=-10", "unknown region 'FR'"),
        (Q + "?model=demand&sector=Fishing&change=-10", "unknown sector 'Fishing'"),
        # a sector with no live node is unknown: paddy rice has x = 0 in both regions of F
        (Q + "?model=demand&sector=Cultivation%20of%20paddy%20rice&change=-10",
         "unknown sector 'Cultivation of paddy rice'"),
        (Q + "?model=foo&node=DE.2&change=-10", None),
        (Q + "?model=demand&node=DE.2&change=-101&unit=pct", None),
        (Q + "?model=demand&node=DE.2&change=-61&unit=meur", None),
        (Q + "?model=demand&node=DE.2&change=-10&unit=pct&top=21", None),
        (Q + "?model=demand&node=DE.2&change=-10&unit=foo", None),
        (Q + "?model=demand&node=DE.2&change=-10&unit=pct&top=0", None),
        (Q + "?model=demand&node=DE.2&change=0&unit=meur", None),
        (Q + "?model=demand&node=DE.2&change=nan&unit=meur", None),
        (Q + "?model=demand&node=DE.2&unit=pct", None),
        (Q + "?model=demand&node=DE.2&change=-10&focus=DE.1", "unknown node 'DE.1'"),
        (P + "?carbon_eur_per_t=100&focus=DE.1", "unknown node 'DE.1'"),
        (P + "?carbon_eur_per_t=-1", None),
        (P + "?carbon_eur_per_t=10001", None),
        (P + "?carbon_eur_per_t=100&region=FR", "unknown region 'FR'"),
    ],
)
def test_bad_requests_are_422(client, path, detail):  # AC-14
    res = client.get(path)
    assert res.status_code == 422, res.text
    if detail:
        assert res.json() == {"detail": detail}


def test_skipped(client_f2):  # AC-20, AC-21, AC-23d
    body = get(client_f2, Q + "?model=demand&node=DE.2&node=CN.3&change=-10&unit=pct")
    assert body["skipped"] == ["CN.3"] and [s["node_id"] for s in body["shocked"]] == ["DE.2"]
    res = client_f2.get(Q + "?model=demand&node=CN.3&change=-10&unit=pct")
    assert (res.status_code, res.json()) == (422, {"detail": "no selected node has a positive base"})
    body = get(client_f2, Q + "?model=demand&node=DE.2&node=CN.3&change=-30&unit=meur")
    assert r4(body["change_pct"]) == -50 and shocked(body) == [("DE.2", 60, -30)] and body["skipped"] == ["CN.3"]


@pytest.mark.parametrize("path", [Q + "?model=demand&node=DE.2&change=-10", P + "?carbon_eur_per_t=100"])
def test_not_built_is_503(monkeypatch, path):  # AC-22
    monkeypatch.delenv("ARP_VALUE_CHAIN_DIR", raising=False)
    res = TestClient(app).get(path)
    assert (res.status_code, res.json()) == (503, {"detail": NOT_BUILT})
