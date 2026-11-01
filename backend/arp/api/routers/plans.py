"""Research Orchestrator API: draft, edit, approve, run and cancel plan scripts."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arp.api.auth import Principal, current_user
from arp.config import Settings, get_settings
from arp.db.session import require_dsn
from arp.orchestration.plan_executor import PlanNotRunnable, cancel_plan, run_plan
from arp.orchestration.plan_planner import PlanRejected, draft_plan
from arp.orchestration.plan_store import PlanNotFound, PlanStore

router = APIRouter(prefix="/api/plans", tags=["plans"])
_running: set[asyncio.Task] = set()  # strong refs: a running plan's task is never garbage-collected


def plan_store() -> PlanStore:
    return PlanStore(require_dsn(get_settings()))


def build_runtime(settings: Settings):
    """The real step functions and review check; tests replace this."""
    from arp.db.runs import RunStore
    from arp.orchestration.plan_steps import build_reviewed, build_steps

    run_store = RunStore(require_dsn(settings), settings.runs_dir)
    return build_steps(settings, run_store), build_reviewed(run_store)


class DraftRequest(BaseModel):
    brief: str


class ScriptRequest(BaseModel):
    script: str


def _get(store: PlanStore, plan_id: str) -> dict:
    try:
        return store.get(plan_id)
    except PlanNotFound as exc:
        raise HTTPException(404, f"Unknown plan: {plan_id}") from exc


@router.post("")
async def create_plan(req: DraftRequest, store: PlanStore = Depends(plan_store)) -> dict:
    from arp.api.deps import get_decision_store, get_llm_client
    from arp.orchestration.plan_planner import planner_context
    from arp.storage.taxonomy_store import TaxonomyStore

    context = planner_context(TaxonomyStore(get_settings().taxonomies_dir).list_all(),
                              get_decision_store().list_frameworks())
    try:
        plan_id = await draft_plan(req.brief, get_llm_client(), store, context)
    except PlanRejected as exc:
        raise HTTPException(422, str(exc)) from exc
    return _get(store, plan_id)


@router.get("")
def list_plans(store: PlanStore = Depends(plan_store)) -> list[dict]:
    return store.list()


@router.get("/{plan_id}")
def get_plan(plan_id: str, store: PlanStore = Depends(plan_store)) -> dict:
    return {**_get(store, plan_id), "calls": store.calls(plan_id)}


@router.put("/{plan_id}")
def edit_plan(plan_id: str, req: ScriptRequest, store: PlanStore = Depends(plan_store)) -> dict:
    if _get(store, plan_id)["status"] in {"running", "awaiting_review"}:
        raise HTTPException(409, "plan is already running")
    try:
        store.update_script(plan_id, req.script)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _get(store, plan_id)


@router.post("/{plan_id}/approve")
def approve_plan(plan_id: str, store: PlanStore = Depends(plan_store),
                 principal: Principal = Depends(current_user)) -> dict:
    if _get(store, plan_id)["status"] != "draft":
        raise HTTPException(409, "only a draft plan can be approved")
    store.approve(plan_id, principal.user_id)
    return _get(store, plan_id)


@router.post("/{plan_id}/run", status_code=202)
async def start_plan(plan_id: str, store: PlanStore = Depends(plan_store)) -> dict:
    status = _get(store, plan_id)["status"]
    if status in {"running", "awaiting_review"}:
        raise HTTPException(409, "plan is already running")
    if status not in {"approved", "failed"}:
        raise HTTPException(409, "plan is not approved")
    steps, reviewed = build_runtime(get_settings())
    task = asyncio.create_task(asyncio.to_thread(run_plan, plan_id, store, steps, reviewed))
    _running.add(task)
    task.add_done_callback(_running.discard)
    return {"plan_id": plan_id, "status": "running"}


@router.post("/{plan_id}/cancel")
def cancel(plan_id: str, store: PlanStore = Depends(plan_store)) -> dict:
    _get(store, plan_id)
    try:
        cancel_plan(plan_id, store)
    except PlanNotRunnable as exc:
        raise HTTPException(409, str(exc)) from exc
    return _get(store, plan_id)
