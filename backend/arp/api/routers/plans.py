"""Research Orchestrator API: draft, edit, approve, run and cancel plan scripts; save them as templates and
instantiate those on another universe."""
from __future__ import annotations

import asyncio
import logging
import math
import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from arp.api.auth import Principal, current_user
from arp.config import Settings, get_settings
from arp.db.session import require_dsn
from arp.orchestration.plan_executor import PlanNotRunnable, cancel_plan, claim_plan, run_plan
from arp.orchestration.plan_planner import PlanRejected, draft_plan, replan_plan
from arp.orchestration.plan_store import PlanNotFound, PlanNotReplannable, PlanNotTemplatable, PlanStore, TemplateNotFound
from arp.orchestration.plan_worker import scan

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/plans", tags=["plans"])
templates_router = APIRouter(prefix="/api/plan-templates", tags=["plans"])
_running: set[asyncio.Task] = set()  # strong refs: the plan worker's task is never garbage-collected


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
    script: str | None = None
    budget_usd: float | None = None  # null removes the budget; leaving the key out keeps it


class TemplateRequest(BaseModel):
    name: str = Field(min_length=1)


class InstantiateRequest(BaseModel):
    source: str
    version: int | None = None  # None: the newest


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
    return {**_get(store, plan_id), "calls": store.audited_calls(plan_id), "spent_usd": store.spent_usd(plan_id)}


@router.put("/{plan_id}")
def edit_plan(plan_id: str, req: ScriptRequest, store: PlanStore = Depends(plan_store)) -> dict:
    """A new script or budget returns the plan to draft for a new approval. A budget alone keeps every stored call."""
    if _get(store, plan_id)["status"] in {"running", "awaiting_review"}:
        raise HTTPException(409, "plan is already running")
    if req.script is None and "budget_usd" not in req.model_fields_set:
        raise HTTPException(422, "send script or budget_usd")
    if req.budget_usd is not None and not (math.isfinite(req.budget_usd) and req.budget_usd >= 0):
        raise HTTPException(422, "budget_usd must be a finite number >= 0, or null for no budget")
    if req.script is not None:
        try:
            store.update_script(plan_id, req.script)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    if "budget_usd" in req.model_fields_set:
        store.set_budget(plan_id, req.budget_usd)
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
    """Claims the plan; the plan worker runs it on its next scan."""
    _get(store, plan_id)
    try:
        await asyncio.to_thread(claim_plan, store, plan_id)
    except PlanNotRunnable as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"plan_id": plan_id, "status": "running"}


def start_plan_worker(settings: Settings) -> asyncio.Task:
    """Started in the API lifespan when `plan_worker_seconds` is above 0; the caller cancels it on shutdown."""
    task = asyncio.create_task(plan_worker(settings))
    _running.add(task)
    task.add_done_callback(_done)
    return task


async def plan_worker(settings: Settings) -> None:
    """The API's plan worker: a scan every `plan_worker_seconds`. Each plan it picks up runs in its own thread, so a
    long plan never holds up a new one; the plan lease keeps two threads off the same plan."""
    store = plan_store()
    steps, reviewed = build_runtime(settings)
    while True:
        try:
            await asyncio.to_thread(scan, store, steps, reviewed, run=_in_thread)
        except Exception:  # noqa: BLE001 - a failed scan (database away) must not end the worker
            logger.exception("plan worker scan failed")
        await asyncio.sleep(settings.plan_worker_seconds)


def _in_thread(*args, **kwargs) -> None:
    def go():
        try:
            run_plan(*args, **kwargs)
        except PlanNotRunnable:
            pass  # another thread or process took it first
        except Exception:  # noqa: BLE001
            logger.exception("plan worker failed")

    threading.Thread(target=go, daemon=True).start()  # daemon: a restart drops it and the next scan resumes the plan


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


@router.post("/{plan_id}/template")
def save_template(plan_id: str, req: TemplateRequest, store: PlanStore = Depends(plan_store),
                  principal: Principal = Depends(current_user)) -> dict:
    _get(store, plan_id)
    try:
        return store.save_template(plan_id, req.name, principal.user_id)
    except PlanNotTemplatable as exc:
        raise HTTPException(409, str(exc)) from exc


@templates_router.get("/{name}")
def get_template(name: str, version: int | None = None, store: PlanStore = Depends(plan_store)) -> dict:
    try:
        return store.template(name, version)
    except TemplateNotFound as exc:
        raise HTTPException(404, "template not found") from exc


@templates_router.post("/{name}/instantiate")
def instantiate_template(name: str, req: InstantiateRequest, store: PlanStore = Depends(plan_store)) -> dict:
    """A draft plan from the template, with `source` in every `universe_build` call; it runs only after approval."""
    try:
        plan_id = store.instantiate(name, req.source, req.version)
    except TemplateNotFound as exc:
        raise HTTPException(404, "template not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _get(store, plan_id)
