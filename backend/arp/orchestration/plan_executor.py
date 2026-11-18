"""Runs an approved plan script for real: each step call starts a run type, waits for it, records it.

Synchronous on purpose: the interpreter is synchronous, so the API runs this in a worker thread and each
adapter drives its own async run with `asyncio.run`. One worker per plan, via the same Postgres advisory
lease runs use. No LLM here.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from arp.errors import NotConfigured
from arp.orchestration.jobs import RunBusy, run_lease
from arp.orchestration.plan_interp import run_script
from arp.orchestration.plan_store import PlanStore, kept_calls

# A step function takes the call's params and returns the result the script sees:
# {"id", "run_id", "companies", ...}; `"gate": True` means its run waits for human review.
StepFn = Callable[..., dict[str, Any]]
ReviewedFn = Callable[[dict[str, Any]], bool]


class PlanNotRunnable(NotConfigured):
    pass


class _Cancelled(Exception):
    pass


class _AwaitingReview(Exception):
    pass


_STARTABLE = {"approved", "failed"}  # failed: `resume` re-runs from the top, reusing finished calls
_ACTIVE = {"running", "awaiting_review"}


def plan_alive(store: PlanStore, plan_id: str) -> bool:
    """A worker holds the plan's lease. A plan left `running` by a dead worker is not alive and may be run again."""
    try:
        with run_lease(store, f"plan:{plan_id}"):
            return False
    except RunBusy:
        return True


def claim_plan(store: PlanStore, plan_id: str) -> None:
    """Mark the plan running before its worker starts, so a caller sees `running` at once and a second claim fails.
    Raises PlanNotRunnable."""
    if store.claim(plan_id, _STARTABLE, "running"):
        return
    status = store.get(plan_id)["status"]
    if status in _ACTIVE and not plan_alive(store, plan_id):
        return  # its worker died; the new worker takes over and resumes
    raise PlanNotRunnable("plan is already running" if status in _ACTIVE else "plan is not approved")


def run_plan(plan_id: str, store: PlanStore, steps: dict[str, StepFn], reviewed: ReviewedFn,
             *, poll_seconds: float = 5.0, return_at_gate: bool = False) -> str:
    """Run the plan to an end state and return it. Raises PlanNotRunnable when it is not approved or already
    running. With `return_at_gate`, a step that waits for review is not waited for: the plan is left
    `awaiting_review` and this returns "awaiting_review"; run it again once the step is reviewed."""
    try:
        with run_lease(store, f"plan:{plan_id}"):
            return _run(plan_id, store, steps, reviewed, poll_seconds, return_at_gate)
    except RunBusy as exc:
        raise PlanNotRunnable("plan is already running") from exc


def _run(plan_id: str, store: PlanStore, steps: dict[str, StepFn], reviewed: ReviewedFn, poll: float,
         return_at_gate: bool) -> str:
    # We hold the lease, so a plan marked running or awaiting review has no other live worker: take it over.
    plan = store.get(plan_id)
    if plan["status"] not in _STARTABLE | _ACTIVE:
        raise PlanNotRunnable("plan is not approved")
    stored = store.calls(plan_id)
    previous = {c["seq"]: c for c in stored}
    kept, first_seq = kept_calls(plan, stored)  # a re-planned plan: finished steps are read, never re-run
    store.set_status(plan_id, "running")

    def status() -> str:
        return store.get(plan_id)["status"]

    def call(kind: str, *, seq: int, **params: Any) -> dict[str, Any]:
        if status() == "cancelled":
            raise _Cancelled
        old = previous.get(seq)
        same = old and old["kind"] == kind and old["params"] == params
        if same and old["status"] == "done":
            return old["result"]
        if same and old["status"] == "awaiting_review":  # its run already exists: never start it twice
            result = old["result"]
        else:
            store.record_call(plan_id, seq=seq, kind=kind, params=params, status="running")
            try:
                result = steps[kind](**params)
            except Exception as exc:
                store.update_call(plan_id, seq, status="failed")
                raise RuntimeError(f"step {seq} {kind} failed: {exc}") from exc
        ids = {"run_id": result.get("run_id"), "result_ref": result.get("result_ref"), "result": result}
        if result.get("gate") and return_at_gate:
            store.update_call(plan_id, seq, status="awaiting_review", **ids)
            if not reviewed({"seq": seq, "kind": kind, **ids}):
                store.claim(plan_id, {"running"}, "awaiting_review")  # atomic: a cancel is never overwritten
                raise _AwaitingReview
        elif result.get("gate"):
            store.update_call(plan_id, seq, status="awaiting_review", **ids)
            if status() != "cancelled":
                store.set_status(plan_id, "awaiting_review")
            row = {"seq": seq, "kind": kind, **ids}
            while not reviewed(row):
                if status() == "cancelled":
                    store.update_call(plan_id, seq, status="cancelled")
                    raise _Cancelled
                time.sleep(poll)
            if not store.claim(plan_id, {"awaiting_review"}, "running"):  # cancelled while it waited
                store.update_call(plan_id, seq, status="done", **ids)
                raise _Cancelled
        store.update_call(plan_id, seq, status="done", **ids)
        return result

    bound = {kind: (lambda k: lambda **kw: call(k, **kw))(kind) for kind in steps}
    try:
        run_script(plan["script"], bound, kept, first_seq)
    except _Cancelled:
        return "cancelled"
    except _AwaitingReview:
        return "awaiting_review"
    except Exception as exc:  # noqa: BLE001 - recorded on the plan; the owner resumes it
        store.set_status(plan_id, "failed", error=str(exc))
        return "failed"
    if status() == "cancelled":  # cancelled during the last step: it finished, nothing else starts
        return "cancelled"
    store.set_status(plan_id, "done")
    return "done"


def cancel_plan(plan_id: str, store: PlanStore) -> None:
    """The step in progress finishes; no later step starts. A step waiting for review is cancelled with it."""
    if store.get(plan_id)["status"] not in {"running", "awaiting_review"}:
        raise PlanNotRunnable("plan is not running")
    store.set_status(plan_id, "cancelled")
    for c in store.calls(plan_id):
        if c["status"] == "awaiting_review":
            store.update_call(plan_id, c["seq"], status="cancelled")
