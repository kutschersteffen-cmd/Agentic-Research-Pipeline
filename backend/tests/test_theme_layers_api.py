from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arp.api.auth import Principal, authorize, current_user
from arp.api.main import app
from arp.cli.theme import theme_app
from arp.config import get_settings
from arp.schemas.common import RunManifest
from tests.theme_layers_helpers import fixture_f, make_theme_run


@pytest.fixture
def client(run_store, tmp_path, monkeypatch):
    monkeypatch.setenv("ARP_RUNS_DIR", str(tmp_path / "runs"))  # the run_store fixture's runs dir
    get_settings.cache_clear()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture
def as_viewer():
    app.dependency_overrides.pop(authorize, None)
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u_viewer", name="viewer", role="viewer")


def _import(csv):
    assert CliRunner().invoke(theme_app, ["edges", "import", "--csv", str(csv)]).exit_code == 0


def _layers(client, run_id="R", as_of="2024-06-30"):
    return client.get(f"/api/themes/runs/{run_id}/layers" + (f"?as_of={as_of}" if as_of else ""))


def test_viewer_gets_settings_and_rows(client, run_store, neo4j_graph, tmp_path, as_viewer):
    keys, csv = fixture_f(run_store, tmp_path)
    _import(csv)
    res = _layers(client)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["run_id"] == "R" and body["as_of"] == "2024-06-30"
    assert body["weights"] == {"w1": 0.45, "w2": 0.35, "w3": 0.2}
    assert (body["decay"], body["max_hops"], body["pure_play_threshold"]) == (0.85, 2, 0.5)
    assert [r["issuer_key"] for r in body["rows"]] == [keys[n] for n in ("A", "B", "S1", "S2", "C")]
    a, s2 = body["rows"][0], body["rows"][3]
    assert a == {
        "issuer_key": keys["A"], "name": "A", "in_run": True, "l1": 0.6, "l2": None, "l3": None,
        "score": 0.27, "pure_play": True, "status": "scored", "rank": 1, "l2_via": None,
    }
    assert (s2["l2"], s2["score"], s2["rank"], s2["l2_via"]) == (0.0867, 0.0303, 4, [keys["S2"], keys["S1"], keys["A"]])


def test_before_publication_lists_run_only(client, run_store, neo4j_graph, tmp_path):
    keys, csv = fixture_f(run_store, tmp_path)
    _import(csv)
    assert [r["issuer_key"] for r in _layers(client, as_of="2024-02-01").json()["rows"]] == [keys[n] for n in ("A", "B", "C")]


def test_unknown_run(client, neo4j_graph):
    res = _layers(client, run_id="nope")
    assert (res.status_code, res.json()["detail"]) == (404, "unknown theme run 'nope'")


def test_run_of_another_type(client, run_store, neo4j_graph):
    run_store.save_manifest(RunManifest(run_id="ext1", run_type="extraction"))
    res = _layers(client, run_id="ext1")
    assert (res.status_code, res.json()["detail"]) == (404, "unknown theme run 'ext1'")


def test_bad_as_of(client, run_store, tmp_path):
    fixture_f(run_store, tmp_path)
    res = _layers(client, as_of="30.06.2024")
    assert (res.status_code, res.json()["detail"]) == (422, "as_of must be a date in YYYY-MM-DD form")


def test_as_of_defaults_to_today(client, run_store, neo4j_graph, tmp_path):
    fixture_f(run_store, tmp_path)
    res = _layers(client, as_of=None)
    assert res.status_code == 200 and res.json()["as_of"] == datetime.now(UTC).date().isoformat()


def test_no_token_is_401(client, monkeypatch):
    app.dependency_overrides.pop(authorize, None)
    app.dependency_overrides.pop(current_user, None)
    monkeypatch.setenv("ARP_AUTH_MODE", "local")
    get_settings.cache_clear()
    res = _layers(client)
    assert (res.status_code, res.json()["detail"]) == (401, "Missing or invalid bearer token")


def test_bad_setting_is_503(client, run_store, neo4j_graph, tmp_path, monkeypatch):
    fixture_f(run_store, tmp_path)
    monkeypatch.setenv("ARP_THEME_LAYER_DECAY", "0")
    get_settings.cache_clear()
    res = _layers(client)
    assert res.status_code == 503 and "ARP_THEME_LAYER_DECAY" in res.json()["detail"]


def test_graph_not_configured_is_503_and_results_unchanged(client, run_store, tmp_path, monkeypatch):
    fixture_f(run_store, tmp_path)
    monkeypatch.delenv("ARP_NEO4J_URI", raising=False)
    get_settings.cache_clear()
    res = _layers(client)
    assert (res.status_code, res.json()["detail"]) == (503, "company graph not configured: set ARP_NEO4J_URI")
    results = client.get("/api/runs/R/results")
    assert results.status_code == 200 and results.json()


def test_graph_unreachable_is_503(client, run_store, tmp_path, monkeypatch):
    fixture_f(run_store, tmp_path)
    monkeypatch.setenv("ARP_NEO4J_URI", "bolt://127.0.0.1:1")
    get_settings.cache_clear()
    res = _layers(client)
    assert res.status_code == 503 and res.json()["detail"].startswith("company graph unavailable:")


def test_run_without_saved_companies_is_empty(client, run_store, neo4j_graph):
    run_store.save_manifest(RunManifest(run_id="old", run_type="theme"))
    res = _layers(client, run_id="old")
    assert res.status_code == 200 and res.json()["rows"] == []


def test_two_include_matches_take_the_highest(client, run_store, neo4j_graph):
    keys = make_theme_run(run_store, "M1", {"M": [(0.20, "catalogue"), (0.50, "extracted")]})
    row = _layers(client, run_id="M1").json()["rows"][0]
    assert (row["issuer_key"], row["l1"], row["score"]) == (keys["M"], 0.5, 0.225)


def test_layer_settings_read_per_request(client, run_store, neo4j_graph, tmp_path, monkeypatch):
    """The settings cache is warm from an earlier request; a changed setting still applies."""
    fixture_f(run_store, tmp_path)
    assert _layers(client).json()["max_hops"] == 2
    monkeypatch.setenv("ARP_THEME_LAYER_MAX_HOPS", "1")
    assert _layers(client).json()["max_hops"] == 1
    monkeypatch.delenv("ARP_NEO4J_URI")
    assert _layers(client).json()["detail"] == "company graph not configured: set ARP_NEO4J_URI"
