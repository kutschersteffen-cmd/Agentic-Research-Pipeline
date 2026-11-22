"""GET /api/plans/{id} gives each call its run's model and cost, for the Agent screen's Audit tab
(agent-panel-code-mode slice 8, AC-33)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.routers import plans
from arp.orchestration.plan_executor import run_plan
from arp.orchestration.plan_store import PlanStore
from tests.test_plan_executor_pg import P3, P3Stubs


@pytest.fixture
def store(pg):
    return PlanStore(pg)


@pytest.fixture
def client(store):
    app = FastAPI()
    app.include_router(plans.router)
    app.dependency_overrides[plans.plan_store] = lambda: store
    with TestClient(app) as c:
        yield c


def test_each_call_carries_its_runs_model_and_cost(store, run_store, client):  # AC-33
    plan_id = store.create("b", P3)
    store.approve(plan_id, "alice")
    assert run_plan(plan_id, store, P3Stubs(run_store).all(), lambda c: True) == "done"
    for seq, cost in ((1, 1.2), (2, 0.3)):
        manifest = run_store.load_manifest(f"r_{seq}")
        manifest.estimated_cost_usd, manifest.model = cost, "claude-sonnet-5-5"
        run_store.save_manifest(manifest)

    calls = client.get(f"/api/plans/{plan_id}").json()["calls"]
    assert [(c["seq"], c["run_id"], c["status"], c["model"], c["estimated_cost_usd"]) for c in calls] == [
        (1, "r_1", "done", "claude-sonnet-5-5", 1.2),
        (2, "r_2", "done", "claude-sonnet-5-5", 0.3),
        (3, "r_3", "done", None, 0.0),
    ]
    assert all(c["started_at"] for c in calls)


def test_a_call_without_a_run_has_no_model_or_cost(store, client):
    plan_id = store.create("b", P3)
    store.record_call(plan_id, seq=1, kind="universe_build", params={}, status="starting")
    [call] = client.get(f"/api/plans/{plan_id}").json()["calls"]
    assert (call["run_id"], call["model"], call["estimated_cost_usd"]) == (None, None, None)
