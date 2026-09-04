from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from arp.agents.calibration_agent import CalibrationAgentScheduler, create_calibration_run, execute_calibration_run
from arp.api.deps import get_calibration_scheduler, get_registry, settings_dep
from arp.config import Settings
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.calibration import CalibrationScheduleConfig
from arp.storage.run_store import RunStore

router = APIRouter(prefix="/api/calibration", tags=["calibration"])


def _run_store(settings: Settings = Depends(settings_dep)) -> RunStore:
    return RunStore(settings.runs_dir)


@router.post("/runs")
async def start_calibration_run(
    run_store: RunStore = Depends(_run_store), registry: DocumentSourceRegistry = Depends(get_registry)
) -> dict:
    """Manual trigger: 'check now' for stale verdicts across every
    completed theme run. Uses the exact same pipeline the automatic
    schedule uses. Only ever logs DriftFlag findings -- never re-runs
    classification or changes any prior verdict itself."""
    run_id = create_calibration_run(run_store, "manual")

    async def _background() -> None:
        await execute_calibration_run(run_id, registry=registry, run_store=run_store)

    asyncio.create_task(_background())
    return {"run_id": run_id}


@router.get("/runs/{run_id}")
def get_calibration_run(run_id: str, run_store: RunStore = Depends(_run_store)) -> dict:
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    return manifest.model_dump(mode="json")


@router.get("/runs/{run_id}/results")
def get_calibration_results(
    run_id: str, offset: int = 0, limit: int = 200, run_store: RunStore = Depends(_run_store)
) -> dict:
    rows = run_store.read_jsonl(run_store.results_path(run_id))
    return {"total": len(rows), "results": rows[offset : offset + limit]}


@router.get("/schedule", response_model=CalibrationScheduleConfig)
def get_schedule(scheduler: CalibrationAgentScheduler = Depends(get_calibration_scheduler)) -> CalibrationScheduleConfig:
    return scheduler.load_config()


@router.put("/schedule", response_model=CalibrationScheduleConfig)
def update_schedule(
    config: CalibrationScheduleConfig, scheduler: CalibrationAgentScheduler = Depends(get_calibration_scheduler)
) -> CalibrationScheduleConfig:
    """Enable/disable and configure the automatic recurring calibration
    pass (interval). Takes effect immediately."""
    scheduler.save_config(config)
    return config
