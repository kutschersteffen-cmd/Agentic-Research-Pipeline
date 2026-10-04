from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arp.api.auth import Principal, current_user
from arp.api.deps import blob_store_dep, get_run_store, publish_store_dep, settings_dep
from arp.api.main import app
from arp.config import Settings
from arp.publish.facts import Release
from arp.storage.run_store import RunStore

REL = Release(
    release_id="rel1", doc_id="d1", content_key="ck", storage_uri="file:///ck", issuer_key="ISS1",
    issuer_scheme="LEI", run_id="r1", published_at="2026-01-01T00:00:00.000000+00:00",
    published_by="u_secret", published_by_role="approver",
)


class StubStore:
    def list_releases(self, *, doc_id=None, run_id=None):
        return [REL]

    def get_release(self, release_id):
        return REL if release_id == "rel1" else None


@pytest.fixture
def env(tmp_path):
    app.dependency_overrides[publish_store_dep] = StubStore
    app.dependency_overrides[blob_store_dep] = lambda: None
    app.dependency_overrides[get_run_store] = lambda: RunStore(tmp_path / "runs")
    yield
    for dep in (publish_store_dep, blob_store_dep, get_run_store, settings_dep, current_user):
        app.dependency_overrides.pop(dep, None)


def test_publish_store_missing_dsn_503(tmp_path):
    app.dependency_overrides[settings_dep] = lambda: Settings(postgres_dsn=None)
    try:
        r = TestClient(app).get("/api/publish/releases")
    finally:
        app.dependency_overrides.pop(settings_dep, None)
    assert r.status_code == 503 and "ARP_POSTGRES_DSN" in r.text


def test_publish_requires_approver(env):
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u_an", name="An", role="analyst")
    assert TestClient(app).post("/api/publish/runs/r1").status_code == 403


def test_unknown_run_404(env):
    assert TestClient(app).post("/api/publish/runs/nope").status_code == 404


@pytest.mark.parametrize("reason", ["", "  "])
def test_withdraw_blank_reason_422(env, reason):
    r = TestClient(app).post("/api/publish/releases/rel1/withdraw", json={"reason": reason})
    assert r.status_code == 422, r.text


def test_withdraw_reason_too_long_422(env):
    r = TestClient(app).post("/api/publish/releases/rel1/withdraw", json={"reason": "x" * 2001})
    assert r.status_code == 422


def test_release_response_has_no_user_id(env):
    r = TestClient(app).get("/api/publish/releases", params={"run_id": "r1"})
    assert r.status_code == 200
    assert "u_secret" not in r.text and 'published_by"' not in r.text
    assert r.json()["releases"][0]["published_by_role"] == "approver"


def test_bad_as_of_400(env):
    assert TestClient(app).get("/api/publish/facts", params={"as_of": "yesterday"}).status_code == 400


def test_cli_publish_run_needs_approver(tmp_path, monkeypatch):
    from arp.cli import publish as cli

    users = tmp_path / "users.json"
    users.write_text(json.dumps({"users": [{"user_id": "u_ana", "name": "Ana", "role": "analyst", "token": "tn"}]}))
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(users_file=users))
    monkeypatch.setenv("ARP_CLI_TOKEN", "tn")
    res = CliRunner().invoke(cli.publish_app, ["run", "--run-id", "r1"])
    assert res.exit_code == 1 and "publishing needs an approver" in res.output
