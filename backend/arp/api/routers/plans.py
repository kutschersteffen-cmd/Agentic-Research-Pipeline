"""Research Orchestrator API: draft, edit, approve, run and cancel plan scripts."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arp.api.auth import Principal, current_user
from arp.config import Settings, get_settings
from arp.db.session import require_dsn
from arp.orchestration.plan_executor import PlanNotRunnable, cancel_plan, claim_plan, run_plan
from arp.orchestration.plan_planner import PlanRejected, draft_plan, replan_plan
from arp.orchestration.plan_store import PlanNotFound, PlanNotReplannable, PlanStore

logger = logging.getLogger(__name__)
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


def _context() -> str:
    from arp.api.deps import get_decision_store, get_index_store
    from arp.orchestration.plan_planner import planner_context
    from arp.storage.taxonomy_store import TaxonomyStore
    from arp.universe import saved_universes

    return planner_context(TaxonomyStore(get_settings().taxonomies_dir).list_all(),
                           get_decision_store().list_frameworks(), get_index_store().list_calibrations(),
                           saved_universes(get_settings().runs_dir))


def _check_sources(steps: list[dict]) -> list[str]:
    """A drafted or re-planned script may only name a saved universe or an existing universe file."""
    from arp.universe import universe_source_errors

    return universe_source_errors(get_settings().runs_dir, steps)


@router.post("")
async def create_plan(req: DraftRequest, store: PlanStore = Depends(plan_store)) -> dict:
    from arp.api.deps import get_llm_client

    try:
        plan_id = await draft_plan(req.brief, get_llm_client(), store, await asyncio.to_thread(_context),
                                 check=_check_sources)
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


@router.post("/{plan_id}/replan")
async def replan(plan_id: str, store: PlanStore = Depends(plan_store),
                 principal: Principal = Depends(current_user)) -> dict:
    """The planner writes a script for the failed plan's remaining work; it comes back as a draft to approve."""
    from arp.api.deps import get_llm_client

    if _get(store, plan_id)["status"] != "failed":
        raise HTTPException(409, "only a failed plan can be re-planned")
    try:
        await replan_plan(plan_id, get_llm_client(), store, await asyncio.to_thread(_context),
                          principal.user_id, check=_check_sources)
    except PlanNotReplannable as exc:
        raise HTTPException(409, str(exc)) from exc
    except PlanRejected as exc:
        raise HTTPException(422, str(exc).splitlines()) from exc
    return _get(store, plan_id)


@router.post("/{plan_id}/run", status_code=202)
async def start_plan(plan_id: str, store: PlanStore = Depends(plan_store)) -> dict:
    _get(store, plan_id)
    try:
        await asyncio.to_thread(claim_plan, store, plan_id)
    except PlanNotRunnable as exc:
        raise HTTPException(409, str(exc)) from exc
    steps, reviewed = build_runtime(get_settings())
    task = asyncio.create_task(_drive(plan_id, store, steps, reviewed))
    _running.add(task)
    task.add_done_callback(_done)
    return {"plan_id": plan_id, "status": "running"}


REVIEW_POLL_SECONDS = 5.0


async def _drive(plan_id: str, store: PlanStore, steps, reviewed) -> None:
    """Run the plan in a worker thread. At a review gate the worker returns and this task polls `reviewed`
    without holding a thread, then starts the worker again; it ends when the plan is no longer waiting."""
    while True:
        try:
            status = await asyncio.to_thread(run_plan, plan_id, store, steps, reviewed, return_at_gate=True)
        except PlanNotRunnable:
            return  # cancelled meanwhile, or another worker took it over
        if status != "awaiting_review":
            return
        while True:
            await asyncio.sleep(REVIEW_POLL_SECONDS)
            if (await asyncio.to_thread(store.get, plan_id))["status"] != "awaiting_review":
                return  # cancelled
            waiting = [c for c in await asyncio.to_thread(store.calls, plan_id) if c["status"] == "awaiting_review"]
            if not waiting or await asyncio.to_thread(reviewed, waiting[0]):
                break
        try:
            await asyncio.to_thread(claim_plan, store, plan_id)
        except PlanNotRunnable:
            return


def _done(task: asyncio.Task) -> None:
    _running.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.error("plan worker failed", exc_info=task.exception())


@router.post("/{plan_id}/cancel")
def cancel(plan_id: str, store: PlanStore = Depends(plan_store)) -> dict:
    _get(store, plan_id)
    try:
        cancel_plan(plan_id, store)
    except PlanNotRunnable as exc:
        raise HTTPException(409, str(exc)) from exc
    return _get(store, plan_id)
