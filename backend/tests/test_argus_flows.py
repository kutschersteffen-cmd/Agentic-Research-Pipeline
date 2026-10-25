"""Argus draft flows: a flow is a JSON file under runs_dir/_flows, readable and changeable by any analyst."""

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import settings_dep
from arp.api.main import app
from arp.config import Settings


@pytest.fixture
def client(tmp_path, pg):
    settings = Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")
    app.dependency_overrides[settings_dep] = lambda: settings
    yield TestClient(app)
    app.dependency_overrides.pop(settings_dep, None)


def test_create_get_list_and_patch(client):
    f = client.post("/api/argus/flows").json()
    assert (f["step"], f["companies"], f["started_by"], f["started_by_name"]) == (1, [], "u_test", "Test")
    assert client.get(f"/api/argus/flows/{f['flow_id']}").json()["flow_id"] == f["flow_id"]
    assert [x["flow_id"] for x in client.get("/api/argus/flows").json()["flows"]] == [f["flow_id"]]
    p = client.patch(f"/api/argus/flows/{f['flow_id']}", json={"identity_run_id": "r9"}).json()
    assert p["identity_run_id"] == "r9"
    assert client.get(f"/api/argus/flows/{f['flow_id']}").json()["identity_run_id"] == "r9"


def test_list_is_newest_first(client):
    a = client.post("/api/argus/flows").json()["flow_id"]
    b = client.post("/api/argus/flows").json()["flow_id"]
    assert [x["flow_id"] for x in client.get("/api/argus/flows").json()["flows"]] == [b, a]


def test_an_unreadable_flow_file_is_skipped(client, tmp_path):
    good = client.post("/api/argus/flows").json()["flow_id"]
    (tmp_path / "runs" / "_flows" / "broken.json").write_text("{")
    assert [x["flow_id"] for x in client.get("/api/argus/flows").json()["flows"]] == [good]


def test_unknown_or_unsafe_flow_is_404(client):
    assert client.get("/api/argus/flows/nope").status_code == 404
    assert client.get("/api/argus/flows/..%2Fx").status_code == 404
    assert client.patch("/api/argus/flows/nope", json={}).status_code == 404


def test_viewer_cannot_create_or_change(client):
    app.dependency_overrides[current_user] = lambda: Principal(user_id="v", name="V", role="viewer")
    assert client.post("/api/argus/flows").status_code == 403
