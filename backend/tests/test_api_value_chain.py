import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arp.api.main import app
from arp.cli import app as cli_app
from tests.value_chain_fixture import write_fixture_f

BASE = "/api/value-chain"
NOT_BUILT = "value chain not built: run arp io build-full and set ARP_VALUE_CHAIN_DIR"
CAVEAT = (
    "EXIOBASE 3.11.2 · 2022 · basic prices, M EUR · now-cast years are estimates · capital goods not included in flows"
)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("vc")
    res = CliRunner().invoke(cli_app, ["io", "build-full", str(write_fixture_f(root)), "--out", str(root / "out")])
    assert res.exit_code == 0, res.output
    return root / "out"


# AC-25 / AC-25b: no key, and a key that would fail every model call; the router must not care.
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


def get(client, path):
    res = client.get(BASE + path)
    assert res.status_code == 200, res.text
    return res.json()


def ids(items):
    return [i["node_id"] for i in items]


def r4(x):
    return round(x, 4)


def test_status(client):  # AC-2
    body = get(client, "/status")
    assert body.pop("built_at").endswith("Z")
    assert body == {
        "edition": "exiobase-IOT_2022_ixi", "version": "3.11.2", "year": 2022, "n_nodes": 6, "n_regions": 2,
        "n_sectors": 3, "caveat": CAVEAT,
    }


def test_suppliers(client):  # AC-3, AC-22d
    body = get(client, "/nodes/CN.2")
    assert body["caveat"] == CAVEAT and body["edition"] == "exiobase-IOT_2022_ixi"
    assert [(i["node_id"], r4(i["direct"]), r4(i["total"])) for i in body["suppliers"]] == [
        ("CN.2", 0.2, 0.2696), ("CN.3", 0.1, 0.1572), ("DE.3", 0.1, 0.1448), ("DE.2", 0, 0.0336),
    ]
    assert body["suppliers"][0] | {"direct": 0, "total": 0} == {
        "node_id": "CN.2", "region": "CN", "region_label": "CN", "sector": "Mining of copper ores and concentrates",
        "direct": 0, "total": 0,
    }
    assert ids(get(client, "/nodes/DE.3")["suppliers"]) == ["DE.2", "DE.3", "CN.3", "CN.2"]


def test_suppliers_exclude_own(client):  # AC-4
    assert ids(get(client, "/nodes/CN.2?exclude_own=true")["suppliers"]) == ["CN.3", "DE.3", "DE.2"]


def test_customers(client):  # AC-5, AC-6
    body = get(client, "/nodes/DE.2")
    assert [(i["node_id"], r4(i["direct"]), r4(i["total"])) for i in body["customers"]] == [
        ("DE.3", 0.2, 0.279), ("CN.3", 0.1, 0.1289), ("DE.2", 0.1, 0.1266), ("CN.2", 0, 0.0336),
    ]
    assert ids(get(client, "/nodes/DE.2?exclude_own=true")["customers"]) == ["DE.3", "CN.3", "CN.2"]


def test_intensities(client):  # AC-7, AC-8, AC-8b
    de3 = get(client, "/nodes/DE.3")
    assert de3["sector"] == "Other business activities"
    assert (de3["ghg_t_per_meur"], de3["energy_tj_per_meur"], de3["jobs_per_meur"], de3["va_share"]) == (0, 0, 10, 0.5)
    assert r4(de3["output_meur"]) == 200
    de2 = get(client, "/nodes/DE.2")
    assert [r4(de2[k]) for k in ("ghg_t_per_meur", "energy_tj_per_meur", "jobs_per_meur", "va_share")] == [
        5, 0.1, 10, 0.3,
    ]
    cn3 = get(client, "/nodes/CN.3")
    assert (r4(cn3["ghg_t_per_meur"]), r4(cn3["jobs_per_meur"])) == (0.27, 10)


def test_direct_order(client):  # AC-22c, AC-22f
    body = get(client, "/nodes/DE.3?order=direct")
    assert ids(body["suppliers"]) == ["CN.3", "DE.2", "DE.3"] and [i["direct"] for i in body["suppliers"]] == [0.1] * 3
    assert ids(body["customers"]) == ["DE.3", "CN.2", "DE.2"]
    assert [r4(i["direct"]) for i in body["customers"]] == [0.1, 0.05, 0.05]


def shape(t):
    return (t["node_id"], r4(t["coef"]), r4(t["chain"]), [shape(c) for c in t["children"]])


def test_tree(client):  # AC-9, AC-22e
    body = get(client, "/nodes/DE.3/tree?depth=2&width=3&cutoff=0.01")
    assert body["caveat"] == CAVEAT and body["edition"] == "exiobase-IOT_2022_ixi"
    assert shape(body) == (
        "DE.3", 1, 1, [
            ("CN.3", 0.1, 0.1, [("CN.2", 0.1, 0.01, []), ("DE.2", 0.1, 0.01, [])]),
            ("DE.2", 0.1, 0.1, [("DE.3", 0.1, 0.01, [])]),
        ],
    )
    assert body["children"][0]["region_label"] == "CN" and body["children"][0]["sector"] == "Other business activities"


@pytest.mark.parametrize(
    "query, expected",
    [
        ("depth=1&width=1", ["CN.3"]),  # AC-10
        ("depth=1&cutoff=0.1", ["CN.3", "DE.2"]),  # AC-11
        ("depth=1&cutoff=0.11", []),  # AC-12
        ("depth=1&goods_only=true", ["DE.2"]),  # AC-13
        ("depth=1&cutoff=0", ["CN.3", "DE.2"]),  # AC-13b
    ],
)
def test_tree_filters(client, query, expected):
    assert ids(get(client, f"/nodes/DE.3/tree?{query}")["children"]) == expected


def test_footprint_ghg(client):  # AC-15, AC-16, AC-17, AC-22e
    body = get(client, "/nodes/DE.3/footprint?indicator=ghg&amount_meur=2")
    assert body["caveat"] == CAVEAT and body["edition"] == "exiobase-IOT_2022_ixi"
    assert (body["indicator"], body["unit"], r4(body["total"]), r4(body["in_home_region"])) == (
        "ghg", "t CO₂e", 1.4955, 0.9328,
    )
    assert [[k, r4(v)] for k, v in body["by_region"]] == [["DE", 1.395], ["CN", 0.1004]]
    assert [[k, r4(v)] for k, v in body["by_sector"]] == [
        ["Mining of copper ores and concentrates", 1.4268], ["Other business activities", 0.0687],
    ]
    top1 = get(client, "/nodes/DE.3/footprint?indicator=ghg&amount_meur=2&top=1")
    assert [[k, r4(v)] for k, v in top1["by_region"]] == [["DE", 1.395]]


def test_footprint_energy_and_jobs(client):  # AC-18, AC-19
    energy = get(client, "/nodes/DE.3/footprint?indicator=energy&amount_meur=2")
    assert (energy["unit"], r4(energy["total"]), r4(energy["in_home_region"])) == ("TJ", 0.0279, 1)
    jobs = get(client, "/nodes/DE.3/footprint?indicator=jobs&amount_meur=2")
    assert (jobs["unit"], r4(jobs["total"])) == ("people", 27.9004)


def test_search(client):  # AC-21, AC-22, AC-22b, AC-22e
    assert get(client, "/nodes?q=paddy")["items"] == []
    copper = get(client, "/nodes?q=copper")
    assert ids(copper["items"]) == ["CN.2", "DE.2"]
    assert copper["caveat"] == CAVEAT and copper["edition"] == "exiobase-IOT_2022_ixi"
    assert copper["items"][0] == {
        "node_id": "CN.2", "region": "CN", "region_label": "CN", "sector": "Mining of copper ores and concentrates",
    }
    assert ids(get(client, "/nodes?q=de")["items"]) == ["DE.2", "DE.3"]
    assert ids(get(client, "/nodes?q=de&limit=1")["items"]) == ["DE.2"]


@pytest.mark.parametrize(
    "path",
    [
        "/nodes/DE.2/tree?depth=5",  # AC-14
        "/nodes/DE.3/tree?depth=0",
        "/nodes/DE.3/tree?width=6",
        "/nodes/DE.3/tree?width=0",
        "/nodes/DE.3/tree?cutoff=1.5",
        "/nodes/DE.3/tree?cutoff=-0.1",
        "/nodes/DE.3/footprint?amount_meur=0",
        "/nodes/DE.3/footprint?amount_meur=inf",
        "/nodes/DE.3/footprint?amount_meur=nan",
        "/nodes/DE.3/footprint?indicator=water",
        "/nodes/DE.3/footprint?top=21",
        "/nodes/DE.3/footprint?top=0",
        "/nodes/DE.3?limit=51",
        "/nodes/DE.3?limit=0",
        "/nodes/DE.3?order=foo",
        "/nodes?q=x&limit=101",
        "/nodes?q=x&limit=0",
        "/nodes",
        "/nodes?q=",
        "/nodes?q=%20",
        "/nodes?q=%20%09",
    ],
)
def test_out_of_range_is_422(client, path):  # AC-22g
    assert client.get(BASE + path).status_code == 422


@pytest.mark.parametrize("path", ["/nodes/DE.1", "/nodes/DE.1/tree", "/nodes/DE.1/footprint"])
def test_unknown_node_is_404(client, path):  # AC-20
    res = client.get(BASE + path)
    assert (res.status_code, res.json()) == (404, {"detail": "unknown node 'DE.1'"})


@pytest.mark.parametrize("node", ["DE.999", "abc"])
def test_other_unknown_ids_are_404(client, node):
    res = client.get(f"{BASE}/nodes/{node}")
    assert (res.status_code, res.json()) == (404, {"detail": f"unknown node '{node}'"})


def test_not_configured_is_503(monkeypatch):  # AC-23
    monkeypatch.delenv("ARP_VALUE_CHAIN_DIR", raising=False)
    res = TestClient(app).get(BASE + "/status")
    assert (res.status_code, res.json()) == (503, {"detail": NOT_BUILT})


def test_empty_dir_is_503(tmp_path, monkeypatch):  # AC-24
    monkeypatch.setenv("ARP_VALUE_CHAIN_DIR", str(tmp_path))
    res = TestClient(app).get(BASE + "/nodes?q=x")
    assert (res.status_code, res.json()) == (503, {"detail": NOT_BUILT})


def test_manifest_without_matrix_is_503(built, tmp_path, monkeypatch):
    partial = tmp_path / "partial"
    partial.mkdir()
    (partial / "manifest.json").write_text((built / "manifest.json").read_text())
    monkeypatch.setenv("ARP_VALUE_CHAIN_DIR", str(partial))
    res = TestClient(app).get(BASE + "/status")
    assert (res.status_code, res.json()) == (503, {"detail": NOT_BUILT})
