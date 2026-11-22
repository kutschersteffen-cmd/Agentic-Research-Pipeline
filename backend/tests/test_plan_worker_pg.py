"""Plan worker: `scan()`, `POST /run` hands over, `arp plan worker` (spec agent-panel-code-mode AC-4..AC-9)."""
from __future__ import annotations

import asyncio
import threading
import time
from collections import Counter

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arp.api.auth import Principal, current_user
from arp.api.routers import plans
from arp.cli import plan as plan_cli
from arp.config import get_settings
from arp.orchestration.plan_executor import Step, claim_plan, run_plan
from arp.orchestration.plan_store import PlanStore
from arp.orchestration.plan_worker import scan

P3 = """u = universe_build(taxonomy_id="t", source="s.csv")
e = extraction(universe_run_id=u.run_id, schema_id="x")
r = report_render(source_ids=[e.run_id])
"""
SEQ = {"universe_build": 1, "extraction": 2, "report_render": 3}


class P3Stubs:
    """s1, s2, s3: `start` returns r_<seq>; each counts its start and finish calls."""

    def __init__(self, gate_seq: int | None = None, slow_start: float = 0.0):
        self.gate_seq, self.slow_start = gate_seq, slow_start
        self.starts: Counter[int] = Counter()
        self.finishes: Counter[int] = Counter()
        self.lock = threading.Lock()

    def steps(self) -> dict[str, Step]:
        def make(seq):
            def start(launch_key, **_):
                with self.lock:
                    self.starts[seq] += 1
                time.sleep(self.slow_start)
                return f"r_{seq}"

            def finish(run_id, **_):
                with self.lock:
                    self.finishes[seq] += 1
                return {"id": run_id, "run_id": run_id, "companies": [], "gate": seq == self.gate_seq}
            return Step(start, finish)
        return {kind: make(seq) for kind, seq in SEQ.items()}


@pytest.fixture
def store(pg, monkeypatch):
    monkeypatch.setenv("ARP_PLAN_WORKER_SECONDS", "0")
    get_settings.cache_clear()
    yield PlanStore(pg)
    get_settings.cache_clear()


def _approved(store) -> str:
    plan_id = store.create("b", P3)
    store.approve(plan_id, "alice")
    return plan_id


def _running(store) -> str:
    plan_id = _approved(store)
    claim_plan(store, plan_id)  # what POST /run does
    return plan_id


def _awaiting_review(store) -> str:
    plan_id = _approved(store)
    status = run_plan(plan_id, store, P3Stubs(gate_seq=2).steps(), lambda c: False, return_at_gate=True)
    assert status == "awaiting_review"
    return plan_id


def test_scan_runs_a_running_plan(store):  # AC-4
    plan_id = _running(store)
    assert scan(store, P3Stubs().steps(), lambda c: True) == [plan_id]
    assert store.get(plan_id)["status"] == "done"


def test_scan_continues_a_reviewed_plan(store):  # AC-5
    plan_id = _awaiting_review(store)
    stubs = P3Stubs(gate_seq=2)
    assert scan(store, stubs.steps(), lambda c: c["seq"] == 2) == [plan_id]
    assert [c["seq"] for c in store.calls(plan_id)] == [1, 2, 3]
    assert store.get(plan_id)["status"] == "done"
    assert stubs.starts[2] == 0  # the reviewed step's run is never started again


def test_scan_leaves_an_unreviewed_plan_waiting(store):  # AC-6
    plan_id = _awaiting_review(store)
    assert scan(store, P3Stubs(gate_seq=2).steps(), lambda c: False) == []
    assert store.get(plan_id)["status"] == "awaiting_review"
    assert [c["seq"] for c in store.calls(plan_id)] == [1, 2]


def test_two_scans_at_once_start_each_step_once(store):  # AC-7
    plan_id = _running(store)
    stubs = P3Stubs(slow_start=0.2)
    steps = stubs.steps()
    barrier = threading.Barrier(2)
    results: list[list[str]] = []

    def go():
        barrier.wait()
        results.append(scan(store, steps, lambda c: True))

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert stubs.starts == {1: 1, 2: 1, 3: 1}
    assert sorted(results) == [[], [plan_id]]
    assert store.get(plan_id)["status"] == "done"


@pytest.fixture
def client(store, monkeypatch):
    stubs = P3Stubs()
    monkeypatch.setattr(plans, "build_runtime", lambda settings: (stubs.steps(), lambda c: True))
    monkeypatch.setattr(plan_cli, "_runtime", lambda: (stubs.steps(), lambda c: True))
    app = FastAPI()
    app.include_router(plans.router)
    app.dependency_overrides[plans.plan_store] = lambda: store
    app.dependency_overrides[current_user] = lambda: Principal(user_id="alice", name="alice", role="approver")
    with TestClient(app) as c:
        yield c


def test_run_hands_over_and_starts_nothing(client, store):  # AC-8, AC-8b
    plan_id = _approved(store)
    res = client.post(f"/api/plans/{plan_id}/run")
    assert (res.status_code, res.json()) == (202, {"plan_id": plan_id, "status": "running"})
    time.sleep(2)
    body = client.get(f"/api/plans/{plan_id}").json()
    assert (body["status"], body["calls"]) == ("running", [])


def test_cli_worker_once_runs_the_plan(client, store):  # AC-9
    plan_id = _approved(store)
    assert client.post(f"/api/plans/{plan_id}/run").status_code == 202
    result = CliRunner().invoke(plan_cli.plan_app, ["worker", "--once"])
    assert result.exit_code == 0, result.stdout
    assert result.stdout.split() == [plan_id]
    assert store.get(plan_id)["status"] == "done"


def test_api_worker_scans_on_its_interval(store, monkeypatch):  # D1: the lifespan scheduler's loop
    stubs = P3Stubs()
    monkeypatch.setattr(plans, "build_runtime", lambda settings: (stubs.steps(), lambda c: True))
    plan_id = _running(store)

    async def go():
        task = asyncio.create_task(plans.plan_worker(get_settings().model_copy(update={"plan_worker_seconds": 0.05})))
        for _ in range(200):
            await asyncio.sleep(0.05)
            if store.get(plan_id)["status"] == "done":
                break
        task.cancel()

    asyncio.run(go())
    assert store.get(plan_id)["status"] == "done"
    assert stubs.starts == {1: 1, 2: 1, 3: 1}


def test_scan_leaves_a_plan_that_failed_after_the_listing(store):  # review of PR #619: no run without a resume
    first, second = _running(store), _running(store)
    steps = P3Stubs().steps()
    inner = steps["universe_build"]

    def start(launch_key, **params):  # while scan() runs the first plan, the second's own worker fails it
        if store.get(second)["status"] == "running":
            store.set_status(second, "failed", error="boom")
        return inner.start(launch_key, **params)

    steps["universe_build"] = Step(start, inner.finish)
    assert scan(store, steps, lambda c: True) == [first]
    assert store.get(second)["status"] == "failed"
    assert store.calls(second) == []


def test_second_run_refused_before_any_worker_picks_it_up(client, store):  # v1 AC-30 under D1
    plan_id = _approved(store)
    assert client.post(f"/api/plans/{plan_id}/run").status_code == 202
    res = client.post(f"/api/plans/{plan_id}/run")
    assert (res.status_code, res.json()) == (409, {"detail": "plan is already running"})
