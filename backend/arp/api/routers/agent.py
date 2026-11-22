"""The Agent screen's routes: the inbox, what waits on a person in the agent lanes (spec agent-panel-code-mode,
Phase 3), and ask threads (Phase 7)."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StringConstraints
from starlette.concurrency import run_in_threadpool

from arp import ask
from arp.api.deps import get_run_store
from arp.api.routers.ask import ERROR_DETAIL, AskDeps, answer, ask_deps
from arp.api.routers.plans import plan_store
from arp.db.runs import RunStore
from arp.orchestration.ask_store import AskStore
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


THREAD_NOT_FOUND = "ask thread not found"


def ask_store(store: PlanStore = Depends(plan_store)) -> AskStore:
    return AskStore(store.dsn)


class AgentAskRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    thread_id: str | None = None


class AskPlanLink(BaseModel):
    plan_id: str
    brief: str
    status: str


class AskExplorationLink(BaseModel):
    exploration_id: str
    question: str
    status: str
    label: str


class AgentAsk(BaseModel):
    id: str
    thread_id: str
    question: str
    standalone_question: str | None
    tool: str | None
    response: ask.AskResponse | None
    error: str | None
    asked_by: str
    created_at: datetime
    plans: list[AskPlanLink]
    explorations: list[AskExplorationLink]


class AskThread(BaseModel):
    thread_id: str
    title: str
    status: Literal["answered", "failed"]
    created_at: datetime
    asks: int


@router.post("/asks", response_model=AgentAsk)
async def post_agent_ask(req: AgentAskRequest, asks: AskStore = Depends(ask_store), d: AskDeps = Depends(ask_deps)) -> dict:
    """One ask, stored in its thread (a new one without `thread_id`). A failed ask is stored and answered with 200."""
    if req.thread_id is not None and not await run_in_threadpool(asks.is_thread, req.thread_id):
        raise HTTPException(404, THREAD_NOT_FOUND)
    history = await run_in_threadpool(asks.history, req.thread_id) if req.thread_id else []
    try:
        response = await answer(ask.AskRequest(question=req.question, history=history), d)
        stored = {"tool": response.tool, "standalone_question": response.standalone_question,
                  "response": response.model_dump(mode="json")}
    except Exception:  # noqa: BLE001 - answer() logged it in the audit store; the thread keeps the turn
        stored = {"error": ERROR_DETAIL}
    return await run_in_threadpool(lambda: asks.add(thread_id=req.thread_id, question=req.question,
                                                    asked_by=d.principal.user_id, **stored))


@router.get("/asks", response_model=list[AgentAsk])
def list_thread_asks(thread_id: str, asks: AskStore = Depends(ask_store)) -> list[dict]:
    """The thread's asks, oldest first."""
    if not asks.is_thread(thread_id):
        raise HTTPException(404, THREAD_NOT_FOUND)
    return asks.thread(thread_id)


@router.get("/ask-threads", response_model=list[AskThread])
def list_ask_threads(asks: AskStore = Depends(ask_store)) -> list[dict]:
    return asks.threads()
