from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from arp.api.company_results import list_company_results
from arp.api.deps import get_decision_store, get_llm_client, get_registry, get_run_store, get_xbrl_source, settings_dep
from arp.api.review_endpoints import (
    ReviewDecisionRequest,
    get_review_decisions,
    get_review_history,
    get_review_queue,
    submit_review,
)
from arp.api.routers.decision import template_for_run
from arp.api.run_scheduling import schedule_llm_run
from arp.config import Settings
from arp.decision.templates import attach_to_run
from arp.extraction.pipeline import create_extraction_run, execute_extraction_run
from arp.extraction.schema_builder import draft_schema
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import DataPointSchema
from arp.storage.decision_store import DecisionStore
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
    decision_framework_id: str | None = Field(default=None, description="Scoring template to score the results with.")
    decision_framework_version: int | None = None


@router.post("/runs")
async def start_extraction_run(
    req: RunRequest,
    settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(get_run_store),
    registry: DocumentSourceRegistry = Depends(get_registry),
    decision_store: DecisionStore = Depends(get_decision_store),
) -> dict:
    companies = req.companies or (load_company_universe(req.universe_path) if req.universe_path else None)
    if not companies:
        raise HTTPException(400, "Provide either `companies` or `universe_path`.")

    schema = req.datapoint_schema
    template = None
    if req.decision_framework_id:
        template = template_for_run(
            decision_store, "extraction", req.decision_framework_id, req.decision_framework_version, [f.name for f in schema.fields]
        )

    def _create() -> str:
        run_id = create_extraction_run(schema, companies, settings, run_store)
        if template is not None:
            attach_to_run(run_store, run_id, template, decision_store.get_audit(template.framework_id, template.version))
        return run_id

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


ExtractionProfile = Literal["custom", "financials", "tnfd", "transition_plan"]


class StartRequest(BaseModel):
    """One way to start any extraction pipeline. `profile` picks the
    pipeline; the fields after it are what that pipeline needs."""

    profile: ExtractionProfile
    datapoint_schema: DataPointSchema | None = Field(default=None, description="custom: the schema to extract.")
    as_of: str | None = Field(default=None, description="tnfd: the reporting period the run covers, e.g. FY2025.")
    companies: list[CompanyRef] | None = None
    universe_path: str | None = None
    decision_framework_id: str | None = Field(default=None, description="Decision Studio framework applied as the run's last step.")
    decision_framework_version: int | None = None


@router.post("/start")
async def start_extraction(
    req: StartRequest,
    settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(get_run_store),
    registry: DocumentSourceRegistry = Depends(get_registry),
    decision_store: DecisionStore = Depends(get_decision_store),
    xbrl_source=Depends(get_xbrl_source),
) -> dict:
    """The single entry point for the extraction pipelines: custom schema,
    financials, TNFD and transition plan. It hands the request to that
    pipeline's own start endpoint, which stays available for existing
    callers. Returns `run_type` so a caller knows which results to read."""
    from arp.api.routers import financials, tnfd, transition_plan

    common = {
        "companies": req.companies,
        "universe_path": req.universe_path,
        "decision_framework_id": req.decision_framework_id,
        "decision_framework_version": req.decision_framework_version,
    }
    stores = {"settings": settings, "run_store": run_store, "registry": registry, "decision_store": decision_store}
    if req.profile == "custom":
        if req.datapoint_schema is None:
            raise HTTPException(400, "The custom profile needs `datapoint_schema`.")
        started, run_type = await start_extraction_run(RunRequest(datapoint_schema=req.datapoint_schema, **common), **stores), "extraction"
    elif req.profile == "financials":
        started = await financials.start_financials_extraction_run(financials.RunRequest(**common), **stores, xbrl_source=xbrl_source)
        run_type = "financials"
    elif req.profile == "tnfd":
        if not req.as_of:
            raise HTTPException(400, "The TNFD profile needs `as_of`, the reporting period the run covers.")
        started, run_type = await tnfd.start_tnfd_extraction_run(tnfd.RunRequest(as_of=req.as_of, **common), **stores), "tnfd"
    else:
        started = await transition_plan.start_transition_plan_run(transition_plan.RunRequest(**common), **stores)
        run_type = "transition_plan"
    return {**started, "run_type": run_type}


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


@router.get("/companies/{company_id}/results")
def get_extraction_results_for_company(company_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    """The company-centric complement to /runs/{run_id}/results -- every
    result this company has ever had across every extraction run, not just
    one run's, for the Data Library's "By company" view."""
    return {"results": list_company_results(run_store, "extraction", company_id)}


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
