"""Showcase fixes, R&D Lab: a plan waiting for review holds no worker thread (spec showcase-themes-fixes, section 2)."""
from __future__ import annotations

import time
from collections import Counter

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.routers import plans
from arp.orchestration.plan_store import PlanStore

GATED = """u = universe_build(taxonomy_id="t", source="u.csv")
e = extraction(universe_run_id=u.run_id, schema_id="s")
d = decision_score(source_run_id=e.run_id)
"""
PLAIN = 'u = universe_build(taxonomy_id="t", source="u.csv")\n'


class World:
    def __init__(self):
        self.reviewed = False
        self.calls: Counter[str] = Counter()

    def steps(self):
        def step(kind, gate=False):
            def fn(**_):
                self.calls[kind] += 1
                return {"id": kind, "run_id": f"r_{kind}", "companies": [], "gate": gate}
            return fn
        return {"universe_build": step("universe_build"), "extraction": step("extraction", gate=True),
                "decision_score": step("decision_score")}


@pytest.fixture
def store(pg):
    return PlanStore(pg)


@pytest.fixture
def world():
    return World()


@pytest.fixture
def client(store, world, monkeypatch):
    monkeypatch.setattr(plans, "build_runtime", lambda settings: (world.steps(), lambda c: world.reviewed))
    monkeypatch.setattr(plans, "REVIEW_POLL_SECONDS", 0.05, raising=False)  # absent before the fix
    app = FastAPI()
    app.include_router(plans.router)
    app.dependency_overrides[plans.plan_store] = lambda: store
    app.dependency_overrides[current_user] = lambda: Principal(user_id="alice", name="alice", role="approver")
    with TestClient(app) as c:
        yield c
        for p in store.list():  # let any worker still waiting (the old blocking wait) end
            if p["status"] in {"running", "awaiting_review"}:
                store.set_status(p["id"], "cancelled")
        world.reviewed = True


def _wait(pred, timeout=10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def _start(client, store, script) -> str:
    plan_id = store.create("b", script)
    store.approve(plan_id, "alice")
    assert client.post(f"/api/plans/{plan_id}/run").status_code == 202
    return plan_id


def _waiting(client, store) -> str:
    plan_id = _start(client, store, GATED)
    assert _wait(lambda: store.get(plan_id)["status"] == "awaiting_review")
    return plan_id


def test_waiting_plans_leave_room_for_others(client, store):  # AC-14
    ids = [_start(client, store, GATED) for _ in range(40)]
    assert _wait(lambda: all(store.get(i)["status"] == "awaiting_review" for i in ids), timeout=30)
    other = _start(client, store, PLAIN)
    assert _wait(lambda: store.get(other)["status"] == "done", timeout=10)


def test_reviewed_plan_continues_by_itself(client, store, world):  # AC-15, AC-16
    plan_id = _waiting(client, store)
    world.reviewed = True
    time.sleep(1.5)  # no API request meanwhile
    assert client.get(f"/api/plans/{plan_id}").json()["status"] == "done"
    assert world.calls == {"universe_build": 1, "extraction": 1, "decision_score": 1}


def test_cancel_while_waiting(client, store, world):  # AC-17, AC-18
    plan_id = _waiting(client, store)
    body = client.post(f"/api/plans/{plan_id}/cancel").json()
    assert body["status"] == "cancelled"
    assert store.calls(plan_id)[1]["status"] == "cancelled"
    world.reviewed = True
    time.sleep(1.0)
    assert [c["seq"] for c in store.calls(plan_id)] == [1, 2]
    assert world.calls["decision_score"] == 0
    assert store.get(plan_id)["status"] == "cancelled"
