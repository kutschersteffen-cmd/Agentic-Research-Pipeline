"""Research Orchestrator executor with stub run types (spec AC-18..AC-29, AC-31, AC-32)."""
from __future__ import annotations

import threading
import time

import pytest

from arp.orchestration.plan_executor import PlanNotRunnable, Step, cancel_plan, run_plan
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
        def start(launch_key, **params):
            self.started.append(kind)
            if kind == self.fail_kind:
                raise RuntimeError("boom")
            self.counter += 1
            return "u_1" if kind == "universe_build" else f"r_{self.counter}"

        def finish(run_id, **params):
            if self.block is not None and kind == "extraction":
                self.block.wait(5)
            out = {"id": run_id if kind == "universe_build" else f"{kind[0]}_{self.counter}", "run_id": run_id,
                   "companies": []}
            if kind == self.gate_kind:
                out["gate"] = True
            return out
        return Step(start, finish)

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


def test_cancel_while_awaiting_review_is_kept(store):  # review: reviewed+cancel must not resume
    plan_id = _approved(store)
    reviewed = threading.Event()
    t = threading.Thread(target=run_plan, args=(plan_id, store, Stubs(gate_kind="extraction").all(),
                                                lambda c: reviewed.is_set()), kwargs={"poll_seconds": 0.2})
    t.start()
    _wait_for(lambda: store.get(plan_id)["status"] == "awaiting_review")
    cancel_plan(plan_id, store)
    reviewed.set()
    t.join(5)
    assert store.get(plan_id)["status"] == "cancelled"
    assert [c["seq"] for c in store.calls(plan_id)] == [1, 2]


def test_plan_left_running_by_dead_worker_can_resume(store):  # review: no stuck plans
    from arp.orchestration.plan_executor import claim_plan

    plan_id = _approved(store)
    store.set_status(plan_id, "running")  # as if the worker died mid-run
    claim_plan(store, plan_id)
    assert run_plan(plan_id, store, Stubs().all(), lambda c: True) == "done"


def test_edit_clears_old_calls(store):  # review: an edited plan must not reuse old results
    plan_id = _approved(store)
    run_plan(plan_id, store, Stubs().all(), lambda c: True)
    store.update_script(plan_id, CHAIN)
    assert store.calls(plan_id) == []


def test_claim_marks_running_before_any_worker(store):  # mutation gap: claim must set "running"
    from arp.orchestration.plan_executor import claim_plan

    plan_id = _approved(store)
    claim_plan(store, plan_id)
    assert store.get(plan_id)["status"] == "running"


# --- agent-panel-code-mode slice 1: start and finish, launch keys, attempts ---

P3 = """u = universe_build(taxonomy_id="t", source="s.csv")
e = extraction(universe_run_id=u.run_id, schema_id="x")
r = report_render(source_ids=[e.run_id])
"""


class P3Stubs:
    """Stub start and finish for P3's three kinds. `start` returns `r_<seq>` (`r_<seq>_a<n>` from attempt 2) and
    writes that run's manifest with its launch key, or returns the run its launch key already has. `raise_once`
    maps (seq, "start" | "finish") to an exception raised once, after `start` wrote its manifest."""

    KINDS = {"universe_build": 1, "extraction": 2, "report_render": 3}

    def __init__(self, run_store, raise_once=None):
        self.run_store, self.raise_once = run_store, dict(raise_once or {})
        self.starts = {1: 0, 2: 0, 3: 0}
        self.finishes = {1: 0, 2: 0, 3: 0}

    def _raise(self, seq, half):
        exc = self.raise_once.pop((seq, half), None)
        if exc is not None:
            raise exc

    def step(self, seq):
        from arp.schemas.common import RunManifest

        def start(launch_key, **params):
            self.starts[seq] += 1
            run_id = self.run_store.find_launch_key(launch_key)
            if run_id is None:
                attempt = launch_key.rsplit(":a", 1)[1]
                run_id = f"r_{seq}" if attempt == "1" else f"r_{seq}_a{attempt}"
                self.run_store.save_manifest(RunManifest(run_id=run_id, run_type="stub",
                                                         params={"launch_key": launch_key}, estimated_cost_usd=0.0))
            self._raise(seq, "start")
            return run_id

        def finish(run_id, **params):
            self.finishes[seq] += 1
            self._raise(seq, "finish")
            return {"id": run_id, "run_id": run_id, "companies": []}
        return Step(start, finish)

    def all(self):
        return {kind: self.step(seq) for kind, seq in self.KINDS.items()}


def _launch_keys(run_store):
    return [m.params["launch_key"] for m in run_store.list_runs("stub")]


def test_crash_in_finish_leaves_run_id_stored_then_resume_attaches(store, run_store):  # AC-1, AC-2
    plan_id = _approved(store, P3)
    stubs = P3Stubs(run_store, {(2, "finish"): SystemExit()})
    with pytest.raises(SystemExit):
        run_plan(plan_id, store, stubs.all(), lambda c: True)
    call = store.calls(plan_id)[1]
    assert (call["status"], call["run_id"]) == ("running", "r_2")  # AC-1
    assert run_plan(plan_id, store, stubs.all(), lambda c: True) == "done"
    assert stubs.starts[2] == 1  # AC-2
    assert store.calls(plan_id)[1]["run_id"] == "r_2"
    assert store.get(plan_id)["status"] == "done"


def test_crash_in_start_after_create_finds_the_run_by_launch_key(store, run_store):  # AC-3
    plan_id = _approved(store, P3)
    stubs = P3Stubs(run_store, {(2, "start"): SystemExit()})
    with pytest.raises(SystemExit):
        run_plan(plan_id, store, stubs.all(), lambda c: True)
    assert store.calls(plan_id)[1]["status"] == "starting"
    assert run_plan(plan_id, store, stubs.all(), lambda c: True) == "done"
    key = f"plan:{plan_id}:v1:2:a1"
    assert _launch_keys(run_store).count(key) == 1
    assert store.calls(plan_id)[1]["run_id"] == "r_2"
    assert store.get(plan_id)["status"] == "done"


def test_failed_start_resumes_as_a_new_attempt(store, run_store):  # AC-3b
    plan_id = _approved(store, P3)
    stubs = P3Stubs(run_store, {(2, "start"): RuntimeError("boom")})
    assert run_plan(plan_id, store, stubs.all(), lambda c: True) == "failed"
    assert run_plan(plan_id, store, stubs.all(), lambda c: True) == "done"
    assert store.calls(plan_id)[1]["attempt"] == 2
    assert stubs.starts[2] == 2
    assert sorted(k for k in _launch_keys(run_store) if ":2:" in k) == [f"plan:{plan_id}:v1:2:a1",
                                                                       f"plan:{plan_id}:v1:2:a2"]


def test_executor_records_starting_then_running_before_finish(store, run_store):  # executor order
    plan_id = _approved(store, P3)
    seen = []
    stubs = P3Stubs(run_store)
    steps = stubs.all()
    inner = steps["extraction"]

    def start(launch_key, **params):
        seen.append(("start", store.calls(plan_id)[1]["status"], store.calls(plan_id)[1]["run_id"]))
        return inner.start(launch_key, **params)

    def finish(run_id, **params):
        seen.append(("finish", store.calls(plan_id)[1]["status"], store.calls(plan_id)[1]["run_id"]))
        return inner.finish(run_id, **params)

    steps["extraction"] = Step(start, finish)
    assert run_plan(plan_id, store, steps, lambda c: True) == "done"
    assert seen == [("start", "starting", None), ("finish", "running", "r_2")]
