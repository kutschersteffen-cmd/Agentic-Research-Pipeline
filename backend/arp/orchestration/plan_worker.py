"""The plan worker: finds plans that need a worker and runs them (spec agent-panel-code-mode, D1).

`POST /api/plans/{id}/run` only claims a plan; `scan()` runs it. The API runs `scan()` every
`ARP_PLAN_WORKER_SECONDS`, and `arp plan worker` runs the same loop in its own process. The plan lease keeps one
worker per plan across both, so a plan left behind by a restart is picked up by the next scan.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from arp.orchestration.plan_executor import PlanNotRunnable, ReviewedFn, run_plan
from arp.orchestration.plan_store import PlanStore


def scan(store: PlanStore, steps: dict[str, Any], reviewed: ReviewedFn, *,
         run: Callable[..., Any] = run_plan) -> list[str]:
    """One pass: run every `running` plan nobody works on, and every `awaiting_review` plan whose waiting call
    `reviewed()` now accepts, each up to its next review gate or end. Returns the ids of the plans it ran.
    `run` is `run_plan` or a function that runs it elsewhere, as the API does so one long plan holds up no other."""
    advanced = []
    for plan_id, status in store.active():
        if status == "awaiting_review":
            waiting = [c for c in store.calls(plan_id) if c["status"] == "awaiting_review"]
            if waiting and not reviewed(waiting[0]):
                continue
        try:
            run(plan_id, store, steps, reviewed, return_at_gate=True)
        except PlanNotRunnable:
            continue  # another worker holds it, or it ended or was cancelled since the listing
        advanced.append(plan_id)
    return advanced

