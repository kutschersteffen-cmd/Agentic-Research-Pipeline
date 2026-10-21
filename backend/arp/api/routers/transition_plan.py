from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from arp.api.auth import Principal, current_user
from arp.api.deps import get_run_store
from arp.api.review_endpoints import (
    ReviewDecisionRequest,
    get_review_decisions,
    get_review_history,
    get_review_queue,
    submit_review,
)
from arp.schemas.transition_plan import TransitionPlanIndicator
from arp.storage.run_store import RunStore
from arp.transition_plan.indicators import load_indicators

router = APIRouter(prefix="/api/transition-plan", tags=["transition-plan"])


@router.get("/indicators", response_model=list[TransitionPlanIndicator])
def list_indicators() -> list[TransitionPlanIndicator]:
    """The 64 fixed assessment indicators (Colesanti Senni et al. 2024) --
    reference data for the UI to render definitions/help text, not
    per-run state."""
    return load_indicators()


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
    rows = run_store.read_results(run_id)
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
    run_id: str, req: ReviewDecisionRequest, run_store: RunStore = Depends(get_run_store),
    principal: Principal = Depends(current_user),
) -> dict:
    return submit_review(
        run_store, run_id, item_key=req.item_key, decision=req.decision, principal=principal,
        edited_value=req.edited_value, comment=req.comment,
    )
