from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from arp.api.deps import get_run_store, settings_dep
from arp.api.review_endpoints import (
    ReviewDecisionRequest,
    get_review_decisions,
    get_review_history,
    get_review_queue,
    submit_review,
)
from arp.config import Settings
from arp.schemas.transition_barrier import (
    BarrierCriterion,
    BarrierScore,
    Pillar,
    Region,
    RegistrySource,
    StalenessReport,
)
from arp.storage.run_store import RunStore
from arp.transition_barrier.dataset import (
    build_matrix,
    filter_scores,
    load_criteria,
    load_source_registry,
    rating_distribution,
    sectors,
    sources_for_criterion,
)
from arp.transition_barrier.refresh.pipeline import (
    RefreshDisabledError,
    create_refresh_run,
    execute_refresh_run,
)
from arp.transition_barrier.refresh.router import coverage_summary
from arp.transition_barrier.staleness import build_staleness_report, staleness_days

router = APIRouter(prefix="/api/transition-barrier", tags=["transition-barrier"])


@router.get("/criteria", response_model=list[BarrierCriterion])
def list_criteria() -> list[BarrierCriterion]:
    """The 35 criteria (9 sectors x 3 constraint pillars) with their metrics,
    H/M/L rubrics and primary sources. Static reference data, not per-run state.
    """
    return load_criteria()


@router.get("/criteria/{code}")
def get_criterion(code: str) -> dict:
    """One criterion, joined with its three regional ratings and its
    deduplicated source records -- what the UI detail drawer needs in one call.
    """
    criterion = next((c for c in load_criteria() if c.code == code), None)
    if criterion is None:
        raise HTTPException(404, f"Unknown criterion code: {code}")
    return {
        "criterion": criterion.model_dump(mode="json"),
        "scores": [s.model_dump(mode="json") for s in filter_scores(code=code)],
        "sources": [s.model_dump(mode="json") for s in sources_for_criterion(code)],
    }


@router.get("/scores", response_model=list[BarrierScore])
def list_scores(
    sector: str | None = None,
    region: Region | None = None,
    pillar: Pillar | None = None,
    rating: str | None = None,
) -> list[BarrierScore]:
    """The 105 matrix cells, optionally filtered. All filters are ANDed."""
    return filter_scores(sector=sector, region=region, pillar=pillar, rating=rating)


@router.get("/matrix")
def get_matrix(settings: Settings = Depends(settings_dep)) -> dict:
    """The full 35x3 grid plus the summary counts the heatmap header shows."""
    grid = build_matrix()
    threshold = settings.transition_barrier_staleness_days
    return {
        "sectors": sectors(),
        "regions": [r.value for r in Region],
        "pillars": [p.value for p in Pillar],
        "criteria": [c.model_dump(mode="json") for c in load_criteria()],
        "cells": {
            code: {
                region: {
                    **score.model_dump(mode="json"),
                    "staleness_days": staleness_days(score),
                    "stale": staleness_days(score) >= threshold,
                }
                for region, score in by_region.items()
            }
            for code, by_region in grid.items()
        },
        "distribution": {
            "overall": rating_distribution(),
            **{r.value: rating_distribution(r) for r in Region},
        },
    }


@router.get("/sources", response_model=list[RegistrySource])
def list_sources() -> list[RegistrySource]:
    """The 86 deduplicated sources behind the matrix."""
    return load_source_registry()


@router.get("/staleness", response_model=StalenessReport)
def get_staleness(settings: Settings = Depends(settings_dep)) -> StalenessReport:
    """Which cells are overdue for re-verification. Independent of confidence."""
    return build_staleness_report(threshold_days=settings.transition_barrier_staleness_days)


@router.get("/refresh/coverage")
def get_refresh_coverage() -> dict:
    """How much of the registry the refresh pipeline can actually automate --
    an honest inventory, including the sources that remain manual.
    """
    return {**coverage_summary(), "enabled_patterns": ["legal_regulatory_text"]}


@router.post("/refresh/runs")
async def start_refresh_run(
    settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(get_run_store),
) -> dict:
    """Re-check the EUR-Lex legal sources against the recorded ratings.

    Rating changes are never applied here -- they land in the run's review
    queue for a human to accept or reject.
    """
    try:
        run_id = create_refresh_run(settings, run_store)
    except RefreshDisabledError as exc:
        raise HTTPException(409, str(exc)) from exc

    asyncio.create_task(execute_refresh_run(run_id, settings=settings, run_store=run_store))
    return {"run_id": run_id, "source_count": coverage_summary()["automatable"]}


@router.get("/refresh/runs/{run_id}")
def get_refresh_run(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    return manifest.model_dump(mode="json")


@router.get("/refresh/runs/{run_id}/results")
def get_refresh_results(
    run_id: str, offset: int = 0, limit: int = 500, run_store: RunStore = Depends(get_run_store)
) -> dict:
    rows = run_store.read_jsonl(run_store.results_path(run_id))
    return {"total": len(rows), "results": rows[offset : offset + limit]}


@router.get("/refresh/runs/{run_id}/review-queue")
def get_refresh_review_queue(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    return get_review_queue(run_store, run_id)


@router.get("/refresh/runs/{run_id}/review-decisions")
def get_refresh_review_decisions(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    return get_review_decisions(run_store, run_id)


@router.get("/refresh/runs/{run_id}/review-history")
def get_refresh_review_history(run_id: str, item_key: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    return get_review_history(run_store, run_id, item_key)


@router.post("/refresh/runs/{run_id}/review")
def submit_refresh_review(
    run_id: str, req: ReviewDecisionRequest, run_store: RunStore = Depends(get_run_store)
) -> dict:
    return submit_review(
        run_store,
        run_id,
        item_key=req.item_key,
        decision=req.decision,
        reviewer=req.reviewer,
        edited_value=req.edited_value,
        comment=req.comment,
    )
