"""The Agent screen's inbox: what waits on a person in the agent lanes (spec agent-panel-code-mode, Phase 3)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from arp.api.deps import get_run_store
from arp.api.routers.plans import plan_store
from arp.db.runs import RunStore
from arp.orchestration.plan_store import PlanStore

router = APIRouter(prefix="/api/agent", tags=["agent"])


class InboxRow(BaseModel):
    kind: Literal["plan_approval", "step_review", "exploration"]
    plan_id: str | None
    seq: int | None
    exploration_id: str | None
    title: str
    href: str


def _step_href(call: dict, run_store: RunStore) -> str:
    """The review route for the call's run; a report's gate (its storyline) is on the Agent screen."""
    manifest = run_store.load_manifest(call["run_id"]) if call["run_id"] and call["kind"] != "report_render" else None
    if manifest is None:
        return f"#/agent/{call['plan_id']}"
    return f"#/review/{manifest.run_type}/{call['run_id']}"


@router.get("/inbox", response_model=list[InboxRow])
def inbox(store: PlanStore = Depends(plan_store), run_store: RunStore = Depends(get_run_store)) -> list[InboxRow]:
    """Draft plans and calls awaiting review, oldest first (a plan by its `created_at`, a call by its `started_at`)."""
    rows = [(p["created_at"], InboxRow(kind="plan_approval", plan_id=p["id"], seq=None, exploration_id=None,
                                       title=p["brief"][:60], href=f"#/agent/{p['id']}"))
            for p in store.list() if p["status"] == "draft"]
    rows += [(c["started_at"], InboxRow(kind="step_review", plan_id=c["plan_id"], seq=c["seq"], exploration_id=None,
                                        title=f"{c['kind']} step {c['seq']}", href=_step_href(c, run_store)))
             for c in store.calls_awaiting_review()]
    return [row for _, row in sorted(rows, key=lambda r: r[0])]
