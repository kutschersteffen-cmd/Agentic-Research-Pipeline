from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arp.api.deps import get_registry, get_run_store, settings_dep
from arp.api.review_endpoints import ReviewDecisionRequest, get_review_decisions, get_review_history, get_review_queue, submit_review
from arp.api.run_scheduling import schedule_llm_run
from arp.config import Settings
from arp.extraction.tnfd_pipeline import create_tnfd_extraction_run, execute_tnfd_extraction_run
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import CompanyRef
from arp.storage.run_store import RunStore
from arp.universe import load_company_universe

router = APIRouter(prefix="/api/tnfd", tags=["tnfd"])


class RunRequest(BaseModel):
    as_of: str
    companies: list[CompanyRef] | None = None
    universe_path: str | None = None


@router.post("/runs")
async def start_tnfd_extraction_run(
    req: RunRequest,
    settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(get_run_store),
    registry: DocumentSourceRegistry = Depends(get_registry),
) -> dict:
    companies = req.companies or (load_company_universe(req.universe_path) if req.universe_path else None)
    if not companies:
        raise HTTPException(400, "Provide either `companies` or `universe_path`.")

    def _create() -> str:
        return create_tnfd_extraction_run(companies, req.as_of, settings, run_store)

    async def _run(run_id: str, llm, verifier_llm) -> None:
        await execute_tnfd_extraction_run(
            run_id, companies, req.as_of, llm=llm, verifier_llm=verifier_llm, registry=registry, settings=settings, run_store=run_store
        )

    run_id = schedule_llm_run(create_fn=_create, run=_run)
    return {"run_id": run_id, "company_count": len(companies)}


@router.get("/runs/{run_id}")
def get_tnfd_extraction_run(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    return manifest.model_dump(mode="json")


@router.get("/runs/{run_id}/results")
def get_tnfd_extraction_results(
    run_id: str, offset: int = 0, limit: int = 200, run_store: RunStore = Depends(get_run_store)
) -> dict:
    rows = run_store.read_jsonl(run_store.results_path(run_id))
    return {"total": len(rows), "results": rows[offset : offset + limit]}


@router.get("/runs/{run_id}/review-queue")
def get_tnfd_review_queue(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    return get_review_queue(run_store, run_id)


@router.get("/runs/{run_id}/review-decisions")
def get_tnfd_review_decisions(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    """Latest decision per item_key (keyed at company_id -- the review unit
    is a company's whole TNFD record, since a misread evidence set usually
    affects more than one section)."""
    return get_review_decisions(run_store, run_id)


@router.get("/runs/{run_id}/review-history")
def get_tnfd_review_history(run_id: str, item_key: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    return get_review_history(run_store, run_id, item_key)


@router.post("/runs/{run_id}/review")
def submit_tnfd_review(
    run_id: str, req: ReviewDecisionRequest, run_store: RunStore = Depends(get_run_store)
) -> dict:
    return submit_review(
        run_store, run_id, item_key=req.item_key, decision=req.decision, reviewer=req.reviewer,
        edited_value=req.edited_value, comment=req.comment,
    )
