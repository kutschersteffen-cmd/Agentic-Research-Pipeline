"""The Agent screen's inbox: what waits on a person in the agent lanes (spec agent-panel-code-mode, Phase 3)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from arp.agent.explorations import ExplorationStore, explore
from arp.api.auth import Principal, current_user
from arp.api.deps import get_run_store, settings_dep
from arp.api.routers.plans import plan_store
from arp.config import Settings
from arp.db.runs import RunStore
from arp.db.session import require_dsn
from arp.errors import NotConfigured
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


class ExplorationRequest(BaseModel):
    question: str = Field(min_length=1)


class ToolCall(BaseModel):
    capability_id: str
    args: Any
    result_bytes: int


class Exploration(BaseModel):
    id: str
    question: str
    code: str
    status: Literal["done", "failed", "timeout"]
    result: Any
    error: str | None
    tool_calls: list[ToolCall]
    model: str | None
    cost_usd: float
    created_at: datetime
    accepted_by: str | None
    accepted_at: datetime | None
    label: Literal["exploratory", "accepted"]


def exploration_store(settings: Settings = Depends(settings_dep)) -> ExplorationStore:
    return ExplorationStore(require_dsn(settings))


@router.post("/explorations", response_model=Exploration)
async def create_exploration(req: ExplorationRequest, store: ExplorationStore = Depends(exploration_store),
                             settings: Settings = Depends(settings_dep),
                             principal: Principal = Depends(current_user)) -> dict:
    """Runs the question's code in the sandbox; answers 200 with the stored exploration whether it ran or failed."""
    try:
        return await explore(store, settings, req.question, principal)
    except NotConfigured:
        raise
    except RuntimeError as exc:
        raise HTTPException(502, f"no code was written for this question: {exc}") from exc
