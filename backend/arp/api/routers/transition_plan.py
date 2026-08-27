from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arp.api.deps import get_registry, get_run_store, settings_dep
from arp.api.review_endpoints import ReviewDecisionRequest, get_review_decisions, get_review_history, get_review_queue, submit_review
from arp.api.run_scheduling import schedule_llm_run
from arp.config import Settings
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import CompanyRef
from arp.schemas.transition_plan import TransitionPlanIndicator
from arp.storage.run_store import RunStore
from arp.transition_plan.indicators import load_indicators
from arp.transition_plan.pipeline import create_transition_plan_run, execute_transition_plan_run
from arp.universe import load_company_universe

router = APIRouter(prefix="/api/transition-plan", tags=["transition-plan"])


@router.get("/indicators", response_model=list[TransitionPlanIndicator])
def list_indicators() -> list[TransitionPlanIndicator]:
    """The 64 fixed assessment indicators (Colesanti Senni et al. 2024) --
    reference data for the UI to render definitions/help text, not
    per-run state."""
    return load_indicators()


class RunRequest(BaseModel):
    companies: list[CompanyRef] | None = None
    universe_path: str | None = None


@router.post("/runs")
async def start_transition_plan_run(
    req: RunRequest,
    settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(get_run_store),
    registry: DocumentSourceRegistry = Depends(get_registry),
) -> dict:
    companies = req.companies or (load_company_universe(req.universe_path) if req.universe_path else None)
    if not companies:
        raise HTTPException(400, "Provide either `companies` or `universe_path`.")

    def _create() -> str:
        return create_transition_plan_run(companies, settings, run_store)

    async def _run(run_id: str, llm, verifier_llm) -> None:
        await execute_transition_plan_run(
            run_id, companies, llm=llm, registry=registry, settings=settings, run_store=run_store
        )

    run_id = schedule_llm_run(create_fn=_create, run=_run)
    return {"run_id": run_id, "company_count": len(companies)}


@router.get("/runs/{run_id}")
def get_transition_plan_run(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    return manifest.model_dump(mode="json")


@router.get("/runs/{run_id}/results")
def get_transition_plan_results(
    run_id: str, offset: int = 0, limit: int = 200, run_store: RunStore = Depends(get_run_store)
) -> dict:
    rows = run_store.read_jsonl(run_store.results_path(run_id))
    return {"total": len(rows), "results": rows[offset : offset + limit]}


@router.get("/runs/{run_id}/review-queue")
def get_transition_plan_review_queue(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    return get_review_queue(run_store, run_id)


@router.get("/runs/{run_id}/review-decisions")
def get_transition_plan_review_decisions(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    return get_review_decisions(run_store, run_id)


@router.get("/runs/{run_id}/review-history")
def get_transition_plan_review_history(
    run_id: str, item_key: str, run_store: RunStore = Depends(get_run_store)
) -> dict:
    return get_review_history(run_store, run_id, item_key)


@router.post("/runs/{run_id}/review")
def submit_transition_plan_review(
    run_id: str, req: ReviewDecisionRequest, run_store: RunStore = Depends(get_run_store)
) -> dict:
    return submit_review(
        run_store, run_id, item_key=req.item_key, decision=req.decision, reviewer=req.reviewer,
        edited_value=req.edited_value, comment=req.comment,
    )
