from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arp.api.deps import get_llm_client, get_registry, get_run_store, settings_dep
from arp.api.review_endpoints import ReviewDecisionRequest, get_review_decisions, get_review_history, get_review_queue, submit_review
from arp.api.run_scheduling import schedule_llm_run
from arp.config import Settings
from arp.extraction.pipeline import create_extraction_run, execute_extraction_run
from arp.extraction.schema_builder import draft_schema
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import DataPointSchema
from arp.storage.run_store import RunStore
from arp.universe import load_company_universe

router = APIRouter(prefix="/api/extraction", tags=["extraction"])


class DraftSchemaRequest(BaseModel):
    criteria_text: str


@router.post("/schemas/draft", response_model=DataPointSchema)
async def draft_schema_endpoint(req: DraftSchemaRequest) -> DataPointSchema:
    """Drafts a DataPointSchema from a plain-language ask (e.g. "green
    capex"). The user reviews/edits fields, instructions, and keywords
    before any run uses this schema; a schema can also be built entirely by
    hand and posted straight to /runs, bypassing this endpoint."""
    llm = get_llm_client()
    schema, _usage = await draft_schema(req.criteria_text, llm)
    return schema


class RunRequest(BaseModel):
    datapoint_schema: DataPointSchema
    companies: list[CompanyRef] | None = None
    universe_path: str | None = None


@router.post("/runs")
async def start_extraction_run(
    req: RunRequest,
    settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(get_run_store),
    registry: DocumentSourceRegistry = Depends(get_registry),
) -> dict:
    companies = req.companies or (load_company_universe(req.universe_path) if req.universe_path else None)
    if not companies:
        raise HTTPException(400, "Provide either `companies` or `universe_path`.")

    schema = req.datapoint_schema

    def _create() -> str:
        return create_extraction_run(schema, companies, settings, run_store)

    async def _run(run_id: str, llm, verifier_llm) -> None:
        await execute_extraction_run(
            run_id,
            schema,
            companies,
            llm=llm,
            verifier_llm=verifier_llm,
            registry=registry,
            settings=settings,
            run_store=run_store,
        )

    run_id = schedule_llm_run(create_fn=_create, run=_run)
    return {"run_id": run_id, "company_count": len(companies)}


@router.get("/runs/{run_id}")
def get_extraction_run(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    return manifest.model_dump(mode="json")


@router.get("/runs/{run_id}/results")
def get_extraction_results(
    run_id: str, offset: int = 0, limit: int = 200, run_store: RunStore = Depends(get_run_store)
) -> dict:
    rows = run_store.read_jsonl(run_store.results_path(run_id))
    return {"total": len(rows), "results": rows[offset : offset + limit]}


@router.get("/runs/{run_id}/review-queue")
def get_extraction_review_queue(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    return get_review_queue(run_store, run_id)


@router.get("/runs/{run_id}/review-decisions")
def get_extraction_review_decisions(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    """Latest decision per item_key across the whole run (company- and
    field-level keys mixed) -- one call so the results table can show
    every field's review status without a request per field."""
    return get_review_decisions(run_store, run_id)


@router.get("/runs/{run_id}/review-history")
def get_extraction_review_history(
    run_id: str, item_key: str, run_store: RunStore = Depends(get_run_store)
) -> dict:
    return get_review_history(run_store, run_id, item_key)


@router.post("/runs/{run_id}/review")
def submit_extraction_review(
    run_id: str, req: ReviewDecisionRequest, run_store: RunStore = Depends(get_run_store)
) -> dict:
    return submit_review(
        run_store, run_id, item_key=req.item_key, decision=req.decision, reviewer=req.reviewer,
        edited_value=req.edited_value, comment=req.comment,
    )
