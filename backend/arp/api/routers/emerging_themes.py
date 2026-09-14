from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arp.api.deps import (
    get_emerging_themes_scheduler,
    get_llm_client,
    get_run_store,
    get_taxonomy_store,
    get_topic_store,
    settings_dep,
)
from arp.config import Settings
from arp.emerging_themes.pipeline import (
    create_emerging_themes_run,
    execute_emerging_themes_run,
    load_candidates_with_status,
    promote_candidate,
    reject_candidate,
)
from arp.emerging_themes.scheduler import EmergingThemesScheduler, default_sources
from arp.llm.base import LLMClient
from arp.schemas.common import CompanyRef
from arp.schemas.emerging_themes import EmergingThemesScheduleConfig
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore
from arp.storage.topic_store import TopicStateStore
from arp.universe import load_company_universe

router = APIRouter(prefix="/api/emerging-themes", tags=["emerging-themes"])


class EmergingThemesRunRequest(BaseModel):
    companies: list[CompanyRef] | None = None
    universe_path: str | None = None


@router.post("/runs")
async def start_emerging_themes_run(
    req: EmergingThemesRunRequest,
    settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(get_run_store),
    topic_store: TopicStateStore = Depends(get_topic_store),
    llm: LLMClient = Depends(get_llm_client),
) -> dict:
    """Manual trigger: scan public news/filings/regulatory flow across the
    given (or referenced) universe for emerging themes. Uses the exact
    same pipeline the automatic schedule uses."""
    companies = req.companies or (load_company_universe(req.universe_path) if req.universe_path else None)
    if not companies:
        raise HTTPException(400, "Provide either `companies` or `universe_path`.")

    run_id = create_emerging_themes_run(run_store, companies, "manual")

    async def _background() -> None:
        await execute_emerging_themes_run(
            run_id, companies, llm=llm, sources=default_sources(settings), settings=settings,
            run_store=run_store, topic_store=topic_store,
        )

    asyncio.create_task(_background())
    return {"run_id": run_id, "company_count": len(companies)}


@router.get("/runs/{run_id}")
def get_emerging_themes_run(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    return manifest.model_dump(mode="json")


@router.get("/runs/{run_id}/candidates")
def list_candidates(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    candidates = load_candidates_with_status(run_store, run_id)
    return {"total": len(candidates), "candidates": [c.model_dump(mode="json") for c in candidates]}


class PromoteRequest(BaseModel):
    taxonomy_id: str | None = None


@router.post("/runs/{run_id}/candidates/{theme_id}/promote")
async def promote(
    run_id: str,
    theme_id: str,
    req: PromoteRequest,
    run_store: RunStore = Depends(get_run_store),
    taxonomy_store: TaxonomyStore = Depends(get_taxonomy_store),
    llm: LLMClient = Depends(get_llm_client),
) -> dict:
    """The human review gate's action -- no candidate reaches the taxonomy
    library without this explicit call."""
    try:
        candidate = await promote_candidate(run_store, taxonomy_store, llm, run_id, theme_id, taxonomy_id=req.taxonomy_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return candidate.model_dump(mode="json")


@router.post("/runs/{run_id}/candidates/{theme_id}/reject")
def reject(run_id: str, theme_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    reject_candidate(run_store, run_id, theme_id)
    return {"theme_id": theme_id, "status": "rejected"}


@router.get("/schedule", response_model=EmergingThemesScheduleConfig)
def get_schedule(scheduler: EmergingThemesScheduler = Depends(get_emerging_themes_scheduler)) -> EmergingThemesScheduleConfig:
    return scheduler.load_config()


@router.put("/schedule", response_model=EmergingThemesScheduleConfig)
def update_schedule(
    config: EmergingThemesScheduleConfig, scheduler: EmergingThemesScheduler = Depends(get_emerging_themes_scheduler)
) -> EmergingThemesScheduleConfig:
    """Enable/disable and configure the automatic recurring scan (interval
    + universe file path). Takes effect immediately."""
    scheduler.save_config(config)
    return config
