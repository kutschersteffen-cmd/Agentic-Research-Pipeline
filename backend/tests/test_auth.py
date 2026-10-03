from __future__ import annotations

import json

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from arp.api.auth import Principal, authorize, load_users, require_role
from arp.api.deps import get_run_store, settings_dep
from arp.api.main import app as real_app
from arp.config import Settings
from arp.storage.run_store import RunStore

USERS = [
    {"token": "tv", "user_id": "u_v", "name": "V", "role": "viewer"},
    {"token": "ta", "user_id": "u_a", "name": "A", "role": "analyst"},
    {"token": "tp", "user_id": "u_p", "name": "P", "role": "approver"},
]


@pytest.fixture
def users_file(tmp_path):
    path = tmp_path / "users.json"
    path.write_text(json.dumps({"users": USERS}))
    return path


def make_app(settings: Settings) -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[settings_dep] = lambda: settings
    app.get("/r", dependencies=[Depends(authorize)])(lambda: {"ok": True})
    app.post("/r", dependencies=[Depends(authorize)])(lambda: {"ok": True})
    app.post("/approve")(lambda user=Depends(require_role("approver")): user)
    return app


@pytest.fixture
def client(users_file, tmp_path):
    return TestClient(make_app(Settings(users_file=users_file, runs_dir=tmp_path / "runs")))


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_missing_header_is_401(client):
    assert client.get("/r").status_code == 401


@pytest.mark.parametrize("header", ["Token abc", "Bearer ", "Bearer"])
def test_malformed_header_is_401(client, header):
    assert client.get("/r", headers={"Authorization": header}).status_code == 401


def test_unknown_token_is_401(client):
    assert client.get("/r", headers=bearer("nope")).status_code == 401


def test_viewer_can_get_but_not_post(client):
    assert client.get("/r", headers=bearer("tv")).status_code == 200
    assert client.post("/r", headers=bearer("tv")).status_code == 403


def test_analyst_can_post(client):
    assert client.post("/r", headers=bearer("ta")).status_code == 200


def test_require_role_approver_rejects_analyst(client):
    assert client.post("/approve", headers=bearer("ta")).status_code == 403
    assert client.post("/approve", headers=bearer("tp")).status_code == 200


def test_dev_bypass_only_from_loopback(users_file, tmp_path):
    app = make_app(Settings(auth_mode="dev", users_file=users_file, runs_dir=tmp_path / "runs"))
    local = TestClient(app, client=("127.0.0.1", 5000)).post("/approve")
    assert local.status_code == 200
    assert Principal(**local.json()) == Principal(user_id="dev", name="dev", role="approver")
    assert TestClient(app, client=("10.0.0.5", 5000)).post("/approve").status_code == 401


def test_missing_users_file_raises(tmp_path):
    path = tmp_path / "absent.json"
    with pytest.raises(RuntimeError, match=str(path)):
        load_users(path)


def test_invalid_users_json_raises(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"users": [{"token": "x", "role": "root"}]}')
    with pytest.raises(RuntimeError, match=str(path)):
        load_users(path)


@pytest.fixture
def real_client(users_file, tmp_path):
    real_app.dependency_overrides.clear()
    real_app.dependency_overrides[settings_dep] = lambda: Settings(users_file=users_file, runs_dir=tmp_path / "runs")
    real_app.dependency_overrides[get_run_store] = lambda: RunStore(tmp_path / "runs")
    yield TestClient(real_app)
    real_app.dependency_overrides.clear()


def test_voting_router_unchanged(real_client):
    # voting is frozen: still mounted without the authorize dependency
    assert real_client.get("/api/voting/runs/r1/review-queue").status_code != 401
    assert real_client.get("/api/themes/runs/r1").status_code == 401


def test_health_open_and_me_returns_principal(real_client):
    assert real_client.get("/api/health").status_code == 200
    assert real_client.get("/api/me").status_code == 401
    r = real_client.get("/api/me", headers=bearer("ta"))
    assert r.json() == {"user_id": "u_a", "name": "A", "role": "analyst"}


def test_invalid_row_error_never_leaks_the_token(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"users": [{"token": "s3cret", "user_id": "u", "name": "N", "role": "root"}]}')
    with pytest.raises(RuntimeError) as err:
        load_users(path)
    assert str(path) in str(err.value)
    assert "s3cret" not in str(err.value)
    assert "s3cret" not in repr(err.value.__cause__)
