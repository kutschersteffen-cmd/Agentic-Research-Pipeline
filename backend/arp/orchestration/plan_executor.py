"""Runs an approved plan script for real: each step call starts a run type, waits for it, records it.

Synchronous on purpose: the interpreter is synchronous, so the API runs this in a worker thread and each
adapter drives its own async run with `asyncio.run`. One worker per plan, via the same Postgres advisory
lease runs use. No LLM here.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from arp.orchestration.jobs import RunBusy, run_lease
from arp.orchestration.plan_interp import run_script
from arp.orchestration.plan_store import PlanStore

# A step function takes the call's params and returns the result the script sees:
# {"id", "run_id", "companies", ...}; `"gate": True` means its run waits for human review.
StepFn = Callable[..., dict[str, Any]]
ReviewedFn = Callable[[dict[str, Any]], bool]


class PlanNotRunnable(RuntimeError):
    pass


class _Cancelled(Exception):
    pass


_STARTABLE = {"approved", "failed"}  # failed: `resume` re-runs from the top, reusing finished calls


def run_plan(plan_id: str, store: PlanStore, steps: dict[str, StepFn], reviewed: ReviewedFn,
             *, poll_seconds: float = 5.0) -> str:
    """Run the plan to an end state and return it. Raises PlanNotRunnable when it is not approved or already
    running."""
    try:
        with run_lease(store, f"plan:{plan_id}"):
            return _run(plan_id, store, steps, reviewed, poll_seconds)
    except RunBusy as exc:
        raise PlanNotRunnable("plan is already running") from exc


def _run(plan_id: str, store: PlanStore, steps: dict[str, StepFn], reviewed: ReviewedFn, poll: float) -> str:
    plan = store.get(plan_id)
    if plan["status"] in {"running", "awaiting_review"}:
        raise PlanNotRunnable("plan is already running")
    if plan["status"] not in _STARTABLE:
        raise PlanNotRunnable("plan is not approved")
    previous = {c["seq"]: c for c in store.calls(plan_id)}
    store.set_status(plan_id, "running")

    def status() -> str:
        return store.get(plan_id)["status"]

    def call(kind: str, *, seq: int, **params: Any) -> dict[str, Any]:
        if status() == "cancelled":
            raise _Cancelled
        old = previous.get(seq)
        if old and old["status"] == "done" and old["kind"] == kind and old["params"] == params:
            return old["result"]
        store.record_call(plan_id, seq=seq, kind=kind, params=params, status="running")
        try:
            result = steps[kind](**params)
        except Exception as exc:
            store.update_call(plan_id, seq, status="failed")
            raise RuntimeError(f"step {seq} {kind} failed: {exc}") from exc
        ids = {"run_id": result.get("run_id"), "result_ref": result.get("result_ref"), "result": result}
        if result.get("gate"):
            store.update_call(plan_id, seq, status="awaiting_review", **ids)
            if status() != "cancelled":
                store.set_status(plan_id, "awaiting_review")
            row = {"seq": seq, "kind": kind, **ids}
            while not reviewed(row):
                if status() == "cancelled":
                    store.update_call(plan_id, seq, status="cancelled")
                    raise _Cancelled
                time.sleep(poll)
            store.set_status(plan_id, "running")
        store.update_call(plan_id, seq, status="done", **ids)
        return result

    bound = {kind: (lambda k: lambda **kw: call(k, **kw))(kind) for kind in steps}
    try:
        run_script(plan["script"], bound)
    except _Cancelled:
        return "cancelled"
    except Exception as exc:  # noqa: BLE001 - recorded on the plan; the owner resumes it
        store.set_status(plan_id, "failed", error=str(exc))
        return "failed"
    if status() == "cancelled":  # cancelled during the last step: it finished, nothing else starts
        return "cancelled"
    store.set_status(plan_id, "done")
    return "done"


def cancel_plan(plan_id: str, store: PlanStore) -> None:
    """The step in progress finishes; no later step starts."""
    if store.get(plan_id)["status"] not in {"running", "awaiting_review"}:
        raise PlanNotRunnable("plan is not running")
    store.set_status(plan_id, "cancelled")
