from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arp.agents.taxonomy_researcher import (
    TaxonomyResearcherScheduler,
    create_taxonomy_research_run,
    execute_taxonomy_research_run,
)
from arp.api.deps import get_llm_client, get_taxonomy_researcher_scheduler, get_taxonomy_store, get_web_search_client, settings_dep
from arp.config import Settings
from arp.schemas.taxonomy_researcher import TaxonomyResearcherScheduleConfig
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore

router = APIRouter(prefix="/api/taxonomy-researcher", tags=["taxonomy-researcher"])


def _run_store(settings: Settings = Depends(settings_dep)) -> RunStore:
    return RunStore(settings.runs_dir)


class TaxonomyResearchRunRequest(BaseModel):
    taxonomy_ids: list[str] | None = None


@router.post("/runs")
async def start_taxonomy_research_run(
    req: TaxonomyResearchRunRequest,
    settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(_run_store),
    taxonomy_store: TaxonomyStore = Depends(get_taxonomy_store),
) -> dict:
    """Manual trigger: 'scan now' for every ratified taxonomy (or just
    `taxonomy_ids`, if given). Uses the exact same pipeline the automatic
    schedule uses. Only ever writes new DRAFT taxonomy versions --
    ratification stays a separate, human-only step."""
    run_id = create_taxonomy_research_run(taxonomy_store, run_store, req.taxonomy_ids, "manual")
    llm = get_llm_client()
    search_client = get_web_search_client()

    async def _background() -> None:
        await execute_taxonomy_research_run(
            run_id, llm=llm, search_client=search_client, settings=settings,
            taxonomy_store=taxonomy_store, run_store=run_store, taxonomy_ids=req.taxonomy_ids,
        )

    asyncio.create_task(_background())
    return {"run_id": run_id}


@router.get("/runs/{run_id}")
def get_taxonomy_research_run(run_id: str, run_store: RunStore = Depends(_run_store)) -> dict:
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    return manifest.model_dump(mode="json")


@router.get("/runs/{run_id}/results")
def get_taxonomy_research_results(
    run_id: str, offset: int = 0, limit: int = 200, run_store: RunStore = Depends(_run_store)
) -> dict:
    rows = run_store.read_jsonl(run_store.results_path(run_id))
    return {"total": len(rows), "results": rows[offset : offset + limit]}


@router.get("/schedule", response_model=TaxonomyResearcherScheduleConfig)
def get_schedule(scheduler: TaxonomyResearcherScheduler = Depends(get_taxonomy_researcher_scheduler)) -> TaxonomyResearcherScheduleConfig:
    return scheduler.load_config()


@router.put("/schedule", response_model=TaxonomyResearcherScheduleConfig)
def update_schedule(
    config: TaxonomyResearcherScheduleConfig, scheduler: TaxonomyResearcherScheduler = Depends(get_taxonomy_researcher_scheduler)
) -> TaxonomyResearcherScheduleConfig:
    """Enable/disable and configure the automatic recurring taxonomy
    research scan (interval + optional taxonomy_ids scope). Takes effect
    immediately."""
    scheduler.save_config(config)
    return config
