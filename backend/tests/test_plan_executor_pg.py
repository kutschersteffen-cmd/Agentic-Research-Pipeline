"""Research Orchestrator executor with stub run types (spec AC-18..AC-29, AC-31, AC-32)."""
from __future__ import annotations

import threading
import time

import pytest

from arp.orchestration.plan_executor import PlanNotRunnable, cancel_plan, run_plan
from arp.orchestration.plan_store import PlanStore

CHAIN = """u = universe_build(taxonomy_id="t_grid storage", source="u.csv")
e = extraction(universe_run_id=u.run_id, schema_id="green_capex")
d = decision_score(source_run_id=e.run_id)
"""


class Stubs:
    def __init__(self, gate_kind=None, fail_kind=None, block: threading.Event | None = None):
        self.gate_kind, self.fail_kind, self.block = gate_kind, fail_kind, block
        self.counter = 0
        self.started: list[str] = []

    def step(self, kind):
        def fn(**params):
            self.started.append(kind)
            if kind == self.fail_kind:
                raise RuntimeError("boom")
            if self.block is not None and kind == "extraction":
                self.block.wait(5)
            self.counter += 1
            out = {"id": f"{kind[0]}_{self.counter}", "run_id": f"r_{self.counter}", "companies": []}
            if kind == "universe_build":
                out["id"] = out["run_id"] = "u_1"
            if kind == self.gate_kind:
                out["gate"] = True
            return out
        return fn

    def all(self):
        return {k: self.step(k) for k in ("universe_build", "extraction", "decision_score")}


@pytest.fixture
def store(pg):
    return PlanStore(pg)


def _approved(store, script=CHAIN):
    plan_id = store.create("b", script)
    store.approve(plan_id, "alice")
    return plan_id


def _wait_for(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return
        time.sleep(0.02)
    raise AssertionError("condition not reached")


def test_refs_resolved_order_and_done(store):  # AC-18, AC-19, AC-20
    plan_id = _approved(store)
    assert run_plan(plan_id, store, Stubs().all(), lambda c: True, poll_seconds=0.01) == "done"
    calls = store.calls(plan_id)
    assert calls[1]["params"]["universe_run_id"] == "u_1"
    assert [c["seq"] for c in sorted(calls, key=lambda c: c["started_at"])] == [1, 2, 3]
    assert store.get(plan_id)["status"] == "done"


def test_draft_is_not_runnable(store):
    plan_id = store.create("b", CHAIN)
    with pytest.raises(PlanNotRunnable, match="plan is not approved"):
        run_plan(plan_id, store, Stubs().all(), lambda c: True)


def test_review_gate_pauses_then_continues(store):  # AC-21..AC-24
    plan_id = _approved(store)
    reviewed = threading.Event()
    t = threading.Thread(target=run_plan, args=(plan_id, store, Stubs(gate_kind="extraction").all(),
                                                lambda c: reviewed.is_set()), kwargs={"poll_seconds": 0.02})
    t.start()
    _wait_for(lambda: store.get(plan_id)["status"] == "awaiting_review")
    assert [c["seq"] for c in store.calls(plan_id)] == [1, 2]
    reviewed.set()
    t.join(5)
    assert store.calls(plan_id)[2]["seq"] == 3
    assert store.get(plan_id)["status"] == "done"


def test_review_gate_resumes_with_running_status(store):  # AC-23, AC-24 (state right after review)
    plan_id = _approved(store)
    reviewed, release = threading.Event(), threading.Event()
    stubs = Stubs(gate_kind="extraction")
    steps = stubs.all()
    inner = steps["decision_score"]
    steps["decision_score"] = lambda **kw: (release.wait(5), inner(**kw))[1]
    t = threading.Thread(target=run_plan, args=(plan_id, store, steps, lambda c: reviewed.is_set()),
                         kwargs={"poll_seconds": 0.02})
    t.start()
    _wait_for(lambda: store.get(plan_id)["status"] == "awaiting_review")
    reviewed.set()
    _wait_for(lambda: len(store.calls(plan_id)) == 3)
    assert store.calls(plan_id)[2]["status"] == "running"
    assert store.get(plan_id)["status"] == "running"
    release.set()
    t.join(5)


def test_failed_step_fails_plan(store):  # AC-25, AC-26, AC-27
    plan_id = _approved(store)
    assert run_plan(plan_id, store, Stubs(fail_kind="extraction").all(), lambda c: True) == "failed"
    assert store.get(plan_id)["status"] == "failed"
    calls = store.calls(plan_id)
    assert calls[1]["status"] == "failed"
    assert [c["seq"] for c in calls] == [1, 2]


def test_resume_reuses_finished_steps(store):  # AC-28, AC-29
    plan_id = _approved(store)
    run_plan(plan_id, store, Stubs(fail_kind="extraction").all(), lambda c: True)
    first = store.calls(plan_id)[0]["run_id"]
    stubs = Stubs()
    stubs.counter = 10
    assert run_plan(plan_id, store, stubs.all(), lambda c: True) == "done"
    calls = store.calls(plan_id)
    assert calls[0]["run_id"] == first
    assert calls[1]["run_id"] not in (None, first)
    assert stubs.started == ["extraction", "decision_score"]


def test_second_run_refused_while_running(store):  # AC-31 (executor level)
    plan_id = _approved(store)
    block = threading.Event()
    t = threading.Thread(target=run_plan, args=(plan_id, store, Stubs(block=block).all(), lambda c: True))
    t.start()
    _wait_for(lambda: store.get(plan_id)["status"] == "running" and len(store.calls(plan_id)) == 2)
    with pytest.raises(PlanNotRunnable, match="plan is already running"):
        run_plan(plan_id, store, Stubs().all(), lambda c: True)
    block.set()
    t.join(5)


def test_cancel_lets_current_step_finish(store):  # AC-32
    plan_id = _approved(store)
    block = threading.Event()
    t = threading.Thread(target=run_plan, args=(plan_id, store, Stubs(block=block).all(), lambda c: True))
    t.start()
    _wait_for(lambda: len(store.calls(plan_id)) == 2)
    cancel_plan(plan_id, store)
    block.set()
    t.join(5)
    assert store.get(plan_id)["status"] == "cancelled"
    calls = store.calls(plan_id)
    assert calls[1]["status"] == "done"
    assert [c["seq"] for c in calls] == [1, 2]
