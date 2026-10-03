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


def _write(tmp_path, rows):
    path = tmp_path / "users.json"
    path.write_text(json.dumps({"users": rows}))
    return path


def test_empty_token_row_refused_at_load(tmp_path):
    with pytest.raises(RuntimeError):
        load_users(_write(tmp_path, [{"token": "", "user_id": "u", "name": "N", "role": "viewer"}]))
    with pytest.raises(RuntimeError):
        load_users(_write(tmp_path, [{"token": "   ", "user_id": "u2", "name": "N", "role": "viewer"}]))


@pytest.mark.parametrize(
    "rows",
    [
        [{"token": "dup-s3cret", "user_id": "u1", "name": "A", "role": "viewer"},
         {"token": "dup-s3cret", "user_id": "u2", "name": "B", "role": "viewer"}],
        [{"token": "one-s3cret", "user_id": "u1", "name": "A", "role": "viewer"},
         {"token": "two-s3cret", "user_id": "u1", "name": "B", "role": "viewer"}],
    ],
)
def test_duplicate_token_or_user_id_refused_without_token_text(tmp_path, rows):
    with pytest.raises(RuntimeError) as err:
        load_users(_write(tmp_path, rows))
    assert "s3cret" not in str(err.value)


def test_bearer_with_nothing_is_401_even_if_lookup_would_match(tmp_path, monkeypatch):
    import arp.api.auth as auth

    # Belt and braces: even a users map that somehow holds "" must not let an empty token in.
    monkeypatch.setattr(auth, "load_users", lambda _p: {"": Principal(user_id="x", name="x", role="approver")})
    client = TestClient(make_app(Settings(users_file=tmp_path / "u.json", runs_dir=tmp_path / "runs")))
    for header in ("Bearer", "Bearer ", "Bearer    "):
        assert client.post("/approve", headers={"Authorization": header}).status_code == 401


def test_default_auth_mode_is_dev():
    assert Settings.model_fields["auth_mode"].default == "dev"


def test_dev_bypass_accepts_trusted_networks_only(users_file, tmp_path):
    settings = Settings(auth_mode="dev", dev_trusted_networks=["172.16.0.0/12"], users_file=users_file, runs_dir=tmp_path / "runs")
    app = make_app(settings)
    inside = TestClient(app, client=("172.18.0.1", 5000)).post("/approve")
    assert inside.status_code == 200 and inside.json()["user_id"] == "dev"
    assert TestClient(app, client=("192.168.1.20", 5000)).post("/approve").status_code == 401
    assert TestClient(app, client=("172.32.0.1", 5000)).post("/approve").status_code == 401
    # a token still works from outside
    assert TestClient(app, client=("192.168.1.20", 5000)).post("/approve", headers=bearer("tp")).status_code == 200


def test_local_mode_ignores_trusted_networks(users_file, tmp_path):
    settings = Settings(auth_mode="local", dev_trusted_networks=["172.16.0.0/12"], users_file=users_file, runs_dir=tmp_path / "runs")
    app = make_app(settings)
    assert TestClient(app, client=("172.18.0.1", 5000)).post("/approve").status_code == 401
    assert TestClient(app, client=("127.0.0.1", 5000)).post("/approve").status_code == 401


def test_dev_trusted_networks_from_env(monkeypatch):
    monkeypatch.setenv("ARP_DEV_TRUSTED_NETWORKS", '["172.16.0.0/12"]')
    assert [str(n) for n in Settings().dev_trusted_networks] == ["172.16.0.0/12"]
    monkeypatch.setenv("ARP_DEV_TRUSTED_NETWORKS", '["not-a-cidr"]')
    with pytest.raises(ValueError):
        Settings()


@pytest.fixture
def dev_client(users_file, tmp_path):
    app = make_app(Settings(auth_mode="dev", users_file=users_file, runs_dir=tmp_path / "runs"))
    return TestClient(app, client=("127.0.0.1", 5000))


def test_dev_bypass_refuses_foreign_origin(dev_client):
    assert dev_client.post("/approve", headers={"Origin": "https://evil.example"}).status_code == 401
    assert dev_client.post("/approve", headers={"Origin": "null"}).status_code == 401


def test_dev_bypass_allows_own_origin_and_no_origin(dev_client):
    assert dev_client.post("/approve", headers={"Origin": "http://localhost:5173"}).status_code == 200
    assert dev_client.post("/approve").status_code == 200


def test_untrusted_host_header_is_400(real_client):
    assert real_client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
    assert real_client.get("/api/health", headers={"Host": "localhost:8000"}).status_code == 200
    # voting sits behind the same host check (not auth): still answers on a trusted host
    assert real_client.get("/api/voting/runs/r1/review-queue").status_code != 400
