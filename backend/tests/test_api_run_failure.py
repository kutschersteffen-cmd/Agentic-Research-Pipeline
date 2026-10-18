from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_run_store, settings_dep
from arp.api.main import app as real_app
from arp.config import Settings
from arp.schemas.common import JobStatus, RunManifest
from arp.storage.run_store import RunStore

USERS = [
    {"token": "tv", "user_id": "u_v", "name": "V", "role": "viewer"},
    {"token": "ta", "user_id": "u_a", "name": "A", "role": "analyst"},
    {"token": "tp", "user_id": "u_p", "name": "P", "role": "approver"},
]


@pytest.fixture
def store(pg, tmp_path):
    return RunStore(pg, tmp_path / "runs")


@pytest.fixture
def client(store, tmp_path):
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({"users": USERS}))
    real_app.dependency_overrides.clear()
    real_app.dependency_overrides[settings_dep] = lambda: Settings(users_file=users_file, runs_dir=tmp_path / "runs")
    real_app.dependency_overrides[get_run_store] = lambda: store
    yield TestClient(real_app)
    real_app.dependency_overrides.clear()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def seed(store, status=JobStatus.FAILED, error=None, run_id="r1"):
    store.save_manifest(RunManifest(run_id=run_id, run_type="extraction", status=status, error=error))
    return run_id


def failure(client, run_id="r1", token="ta"):
    return client.get(f"/api/runs/{run_id}/failure", headers=bearer(token))


def test_failure_of_failed_run(client, store):
    seed(store, error="RuntimeError: provider down")
    store.append_event("r1", {"type": "run_failed", "at": "t", "traceback": "Traceback\nRuntimeError: provider down"})
    r = failure(client)
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == "r1"
    assert body["status"] == "failed"
    assert body["error"] == "RuntimeError: provider down"
    assert "RuntimeError: provider down" in body["traceback"]
    assert body["company_errors"] == []


def test_company_errors_values_and_order_skip_review_rows(client, store):
    seed(store)
    store.append_error("r1", {"key": "C1", "error": "boom1", "traceback": "Traceback\nValueError: boom1"})
    store.append_error("r1", {"key": "C3", "error": "needs review", "review": True})
    store.append_error("r1", {"key": "C2", "error": "boom2", "traceback": "Traceback\nValueError: boom2"})
    errors = failure(client).json()["company_errors"]
    assert [e["key"] for e in errors] == ["C1", "C2"]
    assert [e["error"] for e in errors] == ["boom1", "boom2"]
    assert "ValueError: boom1" in errors[0]["traceback"]
    assert "ValueError: boom2" in errors[1]["traceback"]


def test_row_without_traceback_gives_null(client, store):
    seed(store)
    store.append_error("r1", {"key": "C4", "error": "old failure"})
    assert failure(client).json()["company_errors"] == [{"key": "C4", "error": "old failure", "traceback": None}]


def test_repeated_key_keeps_latest_row(client, store):
    seed(store)
    store.append_error("r1", {"key": "C1", "error": "first"})
    store.append_error("r1", {"key": "C2", "error": "other"})
    store.append_error("r1", {"key": "C1", "error": "second"})
    errors = failure(client).json()["company_errors"]
    assert [(e["key"], e["error"]) for e in errors] == [("C1", "second"), ("C2", "other")]


def test_review_row_after_failure_hides_the_key(client, store):
    seed(store)
    store.append_error("r1", {"key": "C1", "error": "first"})
    store.append_error("r1", {"key": "C1", "review": True})
    store.append_error("r1", {"key": "C2", "error": "other"})
    errors = failure(client).json()["company_errors"]
    assert [(e["key"], e["error"]) for e in errors] == [("C1", "first"), ("C2", "other")]


def test_latest_run_failed_event_wins(client, store):
    seed(store, error="x")
    store.append_event("r1", {"type": "run_failed", "at": "t1", "traceback": "T1"})
    store.append_event("r1", {"type": "run_started", "at": "t2"})
    store.append_event("r1", {"type": "run_failed", "at": "t3", "traceback": "T2"})
    traceback = failure(client).json()["traceback"]
    assert "T2" in traceback
    assert "T1" not in traceback


def test_legacy_failed_run_has_null_traceback(client, store):
    seed(store, error="Boom: x")
    r = failure(client)
    assert r.status_code == 200
    assert r.json()["error"] == "Boom: x"
    assert r.json()["traceback"] is None


def test_completed_run_has_no_failure(client, store):
    seed(store, status=JobStatus.COMPLETED)
    r = failure(client)
    assert r.status_code == 200
    assert r.json() == {"run_id": "r1", "status": "completed", "error": None, "traceback": None, "company_errors": []}


def test_unknown_run_404(client):
    r = failure(client, run_id="nope")
    assert r.status_code == 404
    assert r.json()["detail"] == "Run not found"


def test_viewer_gets_403_analyst_and_approver_200(client, store):
    seed(store, error="x")
    assert failure(client, token="tv").status_code == 403
    assert failure(client, token="ta").status_code == 200
    assert failure(client, token="tp").status_code == 200


def test_errors_endpoint_has_no_traceback(client, store):
    seed(store)
    store.append_error("r1", {"key": "C1", "error": "boom1", "traceback": "Traceback\nValueError: boom1"})
    store.append_error("r1", {"key": "C2", "error": "boom2"})
    r = client.get("/api/runs/r1/errors", headers=bearer("tv"))
    assert r.status_code == 200
    rows = r.json()["errors"]
    assert [(row["key"], row["error"]) for row in rows] == [("C1", "boom1"), ("C2", "boom2")]
    assert all("traceback" not in row for row in rows)
