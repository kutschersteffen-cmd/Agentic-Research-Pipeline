"""Argus draft flows: a flow is a JSON file under runs_dir/_flows, readable and changeable by any analyst."""

import json
from datetime import date

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


def test_new_flow_has_previous_year_and_no_files(client):
    f = client.post("/api/argus/flows").json()
    assert (f["reporting_year"], f["files"], f["decisions"]) == (date.today().year - 1, [], {})


def test_step_never_goes_back(client):
    fid = client.post("/api/argus/flows").json()["flow_id"]
    assert client.patch(f"/api/argus/flows/{fid}", json={"step": 2}).json()["step"] == 2
    assert client.patch(f"/api/argus/flows/{fid}", json={"step": 1}).json()["step"] == 2
    assert client.patch(f"/api/argus/flows/{fid}", json={"step": 6}).status_code == 422


def test_reporting_year_bounds(client):
    fid = client.post("/api/argus/flows").json()["flow_id"]
    assert client.patch(f"/api/argus/flows/{fid}", json={"reporting_year": 2023}).json()["reporting_year"] == 2023
    assert client.patch(f"/api/argus/flows/{fid}", json={"reporting_year": 23}).status_code == 422


def test_unknown_file_key_is_400(client):
    fid = client.post("/api/argus/flows").json()["flow_id"]
    r = client.patch(f"/api/argus/flows/{fid}", json={"decisions": {"../x": "kept"}})
    assert (r.status_code, r.json()["detail"]) == (400, "Unknown file")


def test_slice_2_flow_file_still_opens(client, tmp_path):
    fid = "a" * 32
    flows = tmp_path / "runs" / "_flows"
    flows.mkdir(parents=True)
    (flows / f"{fid}.json").write_text(json.dumps({
        "flow_id": fid, "created_at": "2026-10-20T00:00:00Z", "updated_at": "2026-10-20T00:00:00Z",
        "started_by": "u", "started_by_name": "U", "step": 1, "companies": [], "identity_run_id": None,
    }))
    f = client.get(f"/api/argus/flows/{fid}").json()
    assert (f["reporting_year"], f["files"]) == (date.today().year - 1, [])
