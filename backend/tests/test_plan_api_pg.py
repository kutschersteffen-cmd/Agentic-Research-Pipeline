"""Research Orchestrator API and CLI (spec AC-13..AC-17, AC-30, AC-31)."""
from __future__ import annotations

import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arp.api.auth import Principal, current_user
from arp.api.routers import plans
from arp.cli import plan as plan_cli
from arp.orchestration.plan_store import PlanStore

SCRIPT = 'u = universe_build(taxonomy_id="t", source="u.csv")\ne = extraction(universe_run_id=u.run_id, schema_id="s")\n'


@pytest.fixture
def store(pg):
    return PlanStore(pg)


@pytest.fixture
def gate():
    return threading.Event()


@pytest.fixture
def client(store, gate, monkeypatch):
    def steps():
        def universe_build(**_):
            return {"id": "u_1", "run_id": "u_1", "companies": []}

        def extraction(**_):
            gate.wait(5)
            return {"id": "e_1", "run_id": "r_1", "companies": []}
        return {"universe_build": universe_build, "extraction": extraction}

    monkeypatch.setattr(plans, "build_runtime", lambda settings: (steps(), lambda c: True))
    monkeypatch.setattr(plan_cli, "_runtime", lambda: (steps(), lambda c: True))
    app = FastAPI()
    app.include_router(plans.router)
    app.dependency_overrides[plans.plan_store] = lambda: store
    app.dependency_overrides[current_user] = lambda: Principal(user_id="alice", name="alice", role="approver")
    with TestClient(app) as c:  # one event loop for the whole test, so a started plan keeps running
        yield c
        gate.set()


def _wait(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return
        time.sleep(0.02)
    raise AssertionError("condition not reached")


def test_run_refused_for_draft(client, store):  # AC-13
    plan_id = store.create("b", SCRIPT)
    res = client.post(f"/api/plans/{plan_id}/run")
    assert res.status_code == 409
    assert res.json() == {"detail": "plan is not approved"}


def test_approve_records_user(client, store):  # AC-14
    plan_id = store.create("b", SCRIPT)
    body = client.post(f"/api/plans/{plan_id}/approve").json()
    assert (body["status"], body["approved_by"]) == ("approved", "alice")
    assert body["approved_at"] is not None


def test_edit_resets_approval(client, store):  # AC-15, AC-16, AC-17
    plan_id = store.create("b", SCRIPT)
    client.post(f"/api/plans/{plan_id}/approve")
    edited = SCRIPT + 'universe_build(taxonomy_id="t2", source="u.csv")\n'
    client.put(f"/api/plans/{plan_id}", json={"script": edited})
    body = client.get(f"/api/plans/{plan_id}").json()
    assert body["status"] == "draft"
    assert body["approved_by"] is None and body["approved_at"] is None
    assert [c["kind"] for c in body["dry_run"]].count("universe_build") == 2


def test_rejected_edit_is_422(client, store):
    plan_id = store.create("b", SCRIPT)
    res = client.put(f"/api/plans/{plan_id}", json={"script": "import os\n"})
    assert res.status_code == 422
    assert "line 1: import not allowed" in res.json()["detail"]


def test_run_then_second_run_refused_then_cancel(client, store, gate):  # AC-30, then cancel via API
    plan_id = store.create("b", SCRIPT)
    store.approve(plan_id, "alice")
    assert client.post(f"/api/plans/{plan_id}/run").status_code == 202
    _wait(lambda: len(store.calls(plan_id)) == 2)
    res = client.post(f"/api/plans/{plan_id}/run")
    assert res.status_code == 409
    assert res.json() == {"detail": "plan is already running"}
    assert client.post(f"/api/plans/{plan_id}/cancel").json()["status"] == "cancelled"
    gate.set()
    _wait(lambda: store.calls(plan_id)[1]["status"] == "done")
    assert client.get(f"/api/plans/{plan_id}").json()["status"] == "cancelled"


def test_cli_run_refused_while_running(client, store, gate):  # AC-31
    plan_id = store.create("b", SCRIPT)
    store.approve(plan_id, "alice")
    client.post(f"/api/plans/{plan_id}/run")
    _wait(lambda: len(store.calls(plan_id)) == 2)
    result = CliRunner().invoke(plan_cli.plan_app, ["run", plan_id])
    assert result.exit_code == 1
    assert "plan is already running" in result.stdout
    gate.set()
    _wait(lambda: store.get(plan_id)["status"] == "done")


def test_cli_approve_run_show(client, store, gate):
    gate.set()
    plan_id = store.create("b", SCRIPT)
    runner = CliRunner()
    assert runner.invoke(plan_cli.plan_app, ["approve", plan_id, "--user", "bob"]).exit_code == 0
    result = runner.invoke(plan_cli.plan_app, ["run", plan_id])
    assert result.exit_code == 0 and result.stdout.strip() == "done"
    shown = runner.invoke(plan_cli.plan_app, ["show", plan_id]).stdout
    assert "done  approved by bob" in shown and "call 2 extraction done r_1" in shown
