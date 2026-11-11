"""The API serves the built frontend when ARP_FRONTEND_DIST is set (spec bank-jupyter-launch)."""

import pytest
from fastapi.testclient import TestClient

from arp.api.main import app, mount_frontend
from arp.config import Settings


@pytest.fixture
def dist(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>ARP-TEST-INDEX</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    return tmp_path


@pytest.fixture
def client():
    return TestClient(app, base_url="http://localhost")


@pytest.fixture
def served(dist, client):
    before = list(app.router.routes)
    mount_frontend(app, dist)
    yield client
    app.router.routes[:] = before


def test_root_serves_index(served):
    r = served.get("/")
    assert r.status_code == 200
    assert "ARP-TEST-INDEX" in r.text


@pytest.mark.parametrize("path", ["/", "/assets/app.js"])
def test_frontend_has_isolation_headers(served, path):
    # Decision Studio's rule engine needs a cross-origin isolated page (see frontend/vite.config.ts).
    r = served.get(path)
    assert r.headers["cross-origin-opener-policy"] == "same-origin"
    assert r.headers["cross-origin-embedder-policy"] == "require-corp"


def test_health_still_wins(served):
    r = served.get("/api/health")
    assert (r.status_code, r.json()) == (200, {"status": "ok"})


def test_unknown_api_path_is_json_404(served):
    r = served.get("/api/does-not-exist")
    assert (r.status_code, r.json()) == (404, {"detail": "Not Found"})


def test_docs_and_openapi_unchanged(dist, client):
    paths = ["/docs", "/openapi.json"]
    without = [client.get(p).status_code for p in paths]
    before = list(app.router.routes)
    mount_frontend(app, dist)
    try:
        assert [client.get(p).status_code for p in paths] == without
    finally:
        app.router.routes[:] = before


def test_unset_root_is_404(client):
    before = list(app.router.routes)
    mount_frontend(app, None)
    assert app.router.routes == before
    assert client.get("/").status_code == 404


def test_empty_value_is_unset(tmp_path, monkeypatch):
    monkeypatch.setenv("ARP_FRONTEND_DIST", "")
    assert Settings(_env_file=None, cache_dir=tmp_path).frontend_dist is None


def test_missing_dir_fails(tmp_path):
    with pytest.raises(ValueError, match="ARP_FRONTEND_DIST"):
        Settings(_env_file=None, cache_dir=tmp_path, frontend_dist="/nonexistent")


def test_dir_without_index_fails(tmp_path):
    with pytest.raises(ValueError, match="ARP_FRONTEND_DIST"):
        Settings(_env_file=None, cache_dir=tmp_path, frontend_dist=tmp_path)
