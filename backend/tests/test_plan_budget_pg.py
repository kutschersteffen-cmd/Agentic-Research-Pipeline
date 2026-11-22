"""Plan budget: `budget_usd`, the planner's cost, `spent_usd`, stop before a step (agent-panel-code-mode slice 5,
AC-23 to AC-26b)."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.routers import plans
from arp.llm.base import LLMUsage
from arp.orchestration.plan_executor import Step, run_plan
from arp.orchestration.plan_planner import PlanRejected, draft_plan, replan_plan
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
    app.dependency_overrides[current_user] = lambda: Principal(user_id="alice", name="alice", role="approver")
    with TestClient(app) as c:
        yield c


def _costed(stubs: P3Stubs, costs: dict[int, float]) -> dict[str, Step]:
    """P3's stub steps, each `start` writing its run manifest with `estimated_cost_usd` = costs[seq]."""
    def wrap(seq: int, inner: Step) -> Step:
        def start(launch_key, **params):
            run_id = inner.start(launch_key, **params)
            manifest = stubs.run_store.load_manifest(run_id)
            manifest.estimated_cost_usd = costs[seq]
            stubs.run_store.save_manifest(manifest)
            return run_id
        return Step(start, inner.finish)
    return {kind: wrap(seq, stubs.step(seq)) for kind, seq in P3Stubs.KINDS.items()}


def _p3(store, budget: float | None, planner_cost: float = 0.0) -> str:
    plan_id = store.create("b", P3, planner_cost_usd=planner_cost)
    store.set_budget(plan_id, budget)
    store.approve(plan_id, "alice")
    return plan_id


def test_budget_reached_stops_before_the_next_step(store, run_store):  # AC-23
    plan_id = _p3(store, 1.00)
    stubs = P3Stubs(run_store)
    assert run_plan(plan_id, store, _costed(stubs, {1: 1.20, 2: 0.30, 3: 0.50}), lambda c: True) == "failed"
    plan = store.get(plan_id)
    assert (plan["status"], plan["error"]) == ("failed", "budget reached: spent $1.20 of $1.00")
    assert [c["seq"] for c in store.calls(plan_id)] == [1]
    assert stubs.starts == {1: 1, 2: 0, 3: 0}


def test_spent_sums_the_plans_runs_and_the_planner(store, run_store, client):  # AC-24
    plan_id = _p3(store, 5.00, planner_cost=0.05)
    assert run_plan(plan_id, store, _costed(P3Stubs(run_store), {1: 1.20, 2: 0.30, 3: 0.50}), lambda c: True) == "done"
    body = client.get(f"/api/plans/{plan_id}").json()
    assert (body["status"], body["spent_usd"]) == ("done", 2.05)
    assert (body["budget_usd"], body["planner_cost_usd"]) == (5.0, 0.05)


def test_spent_counts_only_this_plans_runs(store, run_store):
    from arp.schemas.common import RunManifest

    plan_id = _p3(store, None)
    run_store.save_manifest(RunManifest(run_id="other", run_type="stub", estimated_cost_usd=9.0))
    assert store.spent_usd(plan_id) == 0.0
    run_plan(plan_id, store, _costed(P3Stubs(run_store), {1: 1.0, 2: 2.0, 3: 4.0}), lambda c: True)
    assert store.spent_usd(plan_id) == 7.0
    assert store.spent_usd(_p3(store, None, planner_cost=0.25)) == 0.25


def test_raised_budget_resumes_without_rerunning_done_steps(store, run_store, client):  # AC-24b
    plan_id = _p3(store, 1.00)
    stubs = P3Stubs(run_store)
    steps = _costed(stubs, {1: 1.20, 2: 0.30, 3: 0.50})
    assert run_plan(plan_id, store, steps, lambda c: True) == "failed"
    assert client.put(f"/api/plans/{plan_id}", json={"budget_usd": 5}).status_code == 200
    assert client.post(f"/api/plans/{plan_id}/approve").status_code == 200
    assert run_plan(plan_id, store, steps, lambda c: True) == "done"
    assert store.get(plan_id)["status"] == "done"
    assert stubs.starts[1] == 1


def test_budget_put_returns_an_approved_plan_to_draft(store, client):  # AC-25
    plan_id = store.create("b", P3)
    store.approve(plan_id, "alice")
    assert client.put(f"/api/plans/{plan_id}", json={"budget_usd": 3}).status_code == 200
    body = client.get(f"/api/plans/{plan_id}").json()
    assert (body["status"], body["budget_usd"], body["approved_by"], body["approved_at"]) == ("draft", 3.0, None, None)


def test_budget_put_keeps_every_stored_call(store, run_store, client):  # Design: "keeps every stored call"
    plan_id = _p3(store, None)
    run_plan(plan_id, store, _costed(P3Stubs(run_store), {1: 0.1, 2: 0.1, 3: 0.1}), lambda c: True)
    before = store.calls(plan_id)
    body = client.put(f"/api/plans/{plan_id}", json={"budget_usd": 2.5}).json()
    assert (body["status"], body["budget_usd"]) == ("draft", 2.5)
    assert store.calls(plan_id) == before
    assert client.put(f"/api/plans/{plan_id}", json={"budget_usd": None}).json()["budget_usd"] is None


@pytest.mark.parametrize("status", ["running", "awaiting_review"])
def test_budget_put_refused_while_running(store, client, status):  # AC-25b
    plan_id = store.create("b", P3)
    store.set_status(plan_id, status)
    res = client.put(f"/api/plans/{plan_id}", json={"budget_usd": 3})
    assert (res.status_code, res.json()) == (409, {"detail": "plan is already running"})
    assert store.get(plan_id)["budget_usd"] is None


def test_put_without_script_or_budget_is_refused(store, client):
    plan_id = store.create("b", P3)
    store.approve(plan_id, "alice")
    assert client.put(f"/api/plans/{plan_id}", json={}).status_code == 422
    assert store.get(plan_id)["status"] == "approved"


def test_no_budget_never_stops(store, run_store):  # AC-26
    plan_id = _p3(store, None)
    assert run_plan(plan_id, store, _costed(P3Stubs(run_store), {1: 100.0, 2: 100.0, 3: 100.0}),
                    lambda c: True) == "done"
    assert store.get(plan_id)["status"] == "done"


class _Planner:
    """Answers each planner call with the next script and the given usage."""

    def __init__(self, scripts: list[str], usage: LLMUsage):
        self.scripts, self.usage = list(scripts), usage

    async def complete_structured(self, *, system, prompt, output_model, **_):
        return output_model(script=self.scripts.pop(0)), self.usage


SONNET = LLMUsage(model="claude-sonnet-5-5", input_tokens=1_000_000, output_tokens=100_000)


def test_planner_cost_stored_on_the_draft(store):  # AC-26b
    plan_id = asyncio.run(draft_plan("b", _Planner([P3], SONNET), store))
    assert store.get(plan_id)["planner_cost_usd"] == 3.00


def test_planner_cost_counts_a_rejected_attempt(store):
    plan_id = asyncio.run(draft_plan("b", _Planner(["import os", P3], SONNET), store))
    assert store.get(plan_id)["planner_cost_usd"] == 6.00


def test_replan_adds_every_attempt_to_the_plan(store):
    plan_id = store.create("b", P3, planner_cost_usd=3.0)
    store.set_status(plan_id, "failed", error="boom")
    with pytest.raises(PlanRejected):
        asyncio.run(replan_plan(plan_id, _Planner(["import os", "import os"], SONNET), store))
    assert store.get(plan_id)["planner_cost_usd"] == 9.00
    asyncio.run(replan_plan(plan_id, _Planner([P3], SONNET), store))
    assert store.get(plan_id)["planner_cost_usd"] == 12.00
    assert store.spent_usd(plan_id) == 12.00
