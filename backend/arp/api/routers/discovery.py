from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arp.api.deps import get_scheduler, settings_dep
from arp.config import Settings
from arp.discovery.change_detector import ChangeDetector
from arp.discovery.pipeline import create_discovery_run, execute_discovery_run
from arp.discovery.scheduler import DiscoveryScheduler
from arp.schemas.common import CompanyRef, DocType
from arp.schemas.discovery import DiscoveryScheduleConfig
from arp.storage.run_store import RunStore
from arp.universe import load_company_universe

router = APIRouter(prefix="/api/discovery", tags=["discovery"])


def _run_store(settings: Settings = Depends(settings_dep)) -> RunStore:
    return RunStore(settings.runs_dir)


class DiscoveryRunRequest(BaseModel):
    companies: list[CompanyRef] | None = None
    universe_path: str | None = None
    doc_types: list[DocType] | None = None


@router.post("/runs")
async def start_discovery_run(
    req: DiscoveryRunRequest,
    settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(_run_store),
) -> dict:
    """Manual trigger: 'search now' for new/updated investor-disclosure
    documents across the given (or referenced) company universe. Uses the
    exact same pipeline the automatic schedule uses."""
    companies = req.companies or (load_company_universe(req.universe_path) if req.universe_path else None)
    if not companies:
        raise HTTPException(400, "Provide either `companies` or `universe_path`.")

    run_id = create_discovery_run(companies, req.doc_types, "manual", run_store)

    async def _background() -> None:
        await execute_discovery_run(
            run_id, companies, settings=settings, run_store=run_store, doc_types=req.doc_types
        )

    asyncio.create_task(_background())
    return {"run_id": run_id, "company_count": len(companies)}


@router.get("/runs/{run_id}")
def get_discovery_run(run_id: str, run_store: RunStore = Depends(_run_store)) -> dict:
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    return manifest.model_dump(mode="json")


@router.get("/events")
def get_discovery_events(
    since: str | None = None, limit: int = 200, settings: Settings = Depends(settings_dep)
) -> dict:
    """The 'new document' hook feed: new_document / updated_document events
    from every discovery run (manual or scheduled), pollable by the UI or
    any external consumer."""
    events = ChangeDetector.read_recent_events(settings.documents_dir / "_events.jsonl", since=since, limit=limit)
    return {"events": events}


@router.get("/schedule", response_model=DiscoveryScheduleConfig)
def get_schedule(scheduler: DiscoveryScheduler = Depends(get_scheduler)) -> DiscoveryScheduleConfig:
    return scheduler.load_config()


@router.put("/schedule", response_model=DiscoveryScheduleConfig)
def update_schedule(
    config: DiscoveryScheduleConfig, scheduler: DiscoveryScheduler = Depends(get_scheduler)
) -> DiscoveryScheduleConfig:
    """Enable/disable and configure the automatic recurring discovery run
    (interval + universe file path). Takes effect immediately."""
    scheduler.save_config(config)
    return config
