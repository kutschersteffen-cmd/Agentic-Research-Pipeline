from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from arp.api.auth import Principal, current_user, require_role
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
from arp.extraction.steps import ExtractionProfile, StepSettings, pipeline_shape, restart_overrides
from arp.ingestion.registry import DocumentSourceRegistry
from arp.orchestration.review_queue import effective_decisions, record_cosign
from arp.orchestration.step_tally import step_counts
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import DataPointSchema
from arp.storage.decision_store import DecisionStore
from arp.storage.run_store import RunStore
from arp.storage.schema_registry import SchemaRegistry
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


def _registry_for(settings: Settings = Depends(settings_dep)) -> SchemaRegistry:
    return SchemaRegistry(settings.schema_registry_dir)


@router.post("/schemas", response_model=DataPointSchema)
def register_schema(schema: DataPointSchema, registry: SchemaRegistry = Depends(_registry_for)) -> DataPointSchema:
    return registry.save(schema)


@router.get("/schemas")
def list_schemas(registry: SchemaRegistry = Depends(_registry_for)) -> list[dict]:
    return registry.list_index()


@router.get("/schemas/{schema_id}", response_model=DataPointSchema)
def get_schema(schema_id: str, version: int | None = None, registry: SchemaRegistry = Depends(_registry_for)) -> DataPointSchema:
    try:
        return registry.get(schema_id, version)
    except KeyError:
        raise HTTPException(404, "Schema not found") from None


@router.post("/schemas/{schema_id}/versions/{version}/release", response_model=DataPointSchema)
def release_schema(
    schema_id: str, version: int, registry: SchemaRegistry = Depends(_registry_for),
    principal: Principal = Depends(require_role("approver")),
) -> DataPointSchema:
    try:
        return registry.release(schema_id, version)
    except KeyError:
        raise HTTPException(404, "Schema not found") from None


class RunRequest(BaseModel):
    datapoint_schema: DataPointSchema
    trial: bool = Field(default=False, description="Allow a schema with draft fields; the run is marked as a trial.")
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
        run_id = create_extraction_run(schema, companies, settings, run_store, trial=req.trial)
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

    run_id = schedule_llm_run(create_fn=_create, run=_run, settings=settings)
    return {"run_id": run_id, "company_count": len(companies)}


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
    step_settings: StepSettings | None = Field(default=None, description="Per-run step settings from the node editor.")
    trial: bool = Field(default=False, description="custom: allow draft fields; the run is marked as a trial.")


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
    financials, TNFD and transition plan, over a batch or a single company.
    It hands the request to that pipeline's own start endpoint, which stays
    available for existing callers. Returns `run_type` so a caller knows
    which results to read."""
    if req.step_settings:
        settings = req.step_settings.apply(settings)
    return await _dispatch(req, settings, run_store, registry, decision_store, xbrl_source)


async def _dispatch(req: StartRequest, settings: Settings, run_store: RunStore, registry, decision_store, xbrl_source) -> dict:
    from arp.api.routers import financials, tnfd, transition_plan

    companies = req.companies or (load_company_universe(req.universe_path) if req.universe_path else None)
    if not companies:
        raise HTTPException(400, "Provide either `companies` or `universe_path`.")
    common = {
        "companies": companies,
        "decision_framework_id": req.decision_framework_id,
        "decision_framework_version": req.decision_framework_version,
    }
    stores = {"settings": settings, "run_store": run_store, "registry": registry, "decision_store": decision_store}
    if req.profile == "custom":
        if req.datapoint_schema is None:
            raise HTTPException(400, "The custom profile needs `datapoint_schema`.")
        started, run_type = await start_extraction_run(RunRequest(datapoint_schema=req.datapoint_schema, trial=req.trial, **common), **stores), "extraction"
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
    run_dir = run_store.run_dir(started["run_id"])
    # What the run used, overrides or not, for its step view; and what it
    # was started with, companies resolved, so it can be restarted.
    (run_dir / "step_settings.json").write_text(StepSettings.effective(settings).model_dump_json())
    saved = req.model_copy(update={"companies": companies, "universe_path": None, "step_settings": StepSettings.effective(settings)})
    (run_dir / "start_request.json").write_text(saved.model_dump_json())
    return {**started, "run_type": run_type}


@router.get("/pipeline")
def get_pipeline(profile: ExtractionProfile, settings: Settings = Depends(settings_dep)) -> dict:
    """The profile's steps for the node editor: nodes, edges, the settings
    each node exposes, and the app's current values for them."""
    return pipeline_shape(profile, settings)


def _manifest_or_404(run_store: RunStore, run_id: str):
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    return manifest


def _saved(run_store: RunStore, run_id: str, name: str) -> str | None:
    path = run_store.run_dir(run_id) / name
    return path.read_text() if path.exists() else None


@router.get("/runs/{run_id}/steps")
def get_run_steps(run_id: str, company_id: str | None = None, run_store: RunStore = Depends(get_run_store)) -> dict:
    """How many items went through each step and the seconds they spent
    there, for the run or one company, live while the run executes; the
    step settings it was started with (null for runs started before the
    node editor, or not through /start); and the run it restarted, if any."""
    _manifest_or_404(run_store, run_id)
    view, live = step_counts(run_store, run_id, company_id)
    settings = _saved(run_store, run_id, "step_settings.json")
    restarted = _saved(run_store, run_id, "restarted_from.json")
    return {
        **view,
        "live": live,
        "settings": StepSettings.model_validate_json(settings) if settings else None,
        "restarted_from": json.loads(restarted) if restarted else None,
        "restartable": _saved(run_store, run_id, "start_request.json") is not None,
    }


@router.get("/runs/{run_id}/companies")
def get_run_companies(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    """Every company in the run with where it stands: done, failed, in
    review (a step before extraction stopped it, with an error report in
    the review queue), or still waiting (queued or in flight)."""
    _manifest_or_404(run_store, run_id)
    saved = _saved(run_store, run_id, "start_request.json")
    done = {r.get("company_id") for r in run_store.read_jsonl(run_store.results_path(run_id))}
    errors = run_store.read_jsonl(run_store.errors_path(run_id))
    review = {r.get("key") for r in errors if r.get("review")} - done
    failed = {r.get("key") for r in errors} - done - review
    if saved:
        companies = StartRequest.model_validate_json(saved).companies or []
        rows = [{"company_id": c.company_id, "name": c.name} for c in companies]
    else:  # a run started before /start saved its companies: only those with an outcome
        rows = [{"company_id": r.get("company_id"), "name": r.get("name")} for r in run_store.read_jsonl(run_store.results_path(run_id))]
        rows += [{"company_id": k, "name": k} for k in failed | review]
    for row in rows:
        cid = row["company_id"]
        row["status"] = "done" if cid in done else "review" if cid in review else "failed" if cid in failed else "waiting"
    return {"companies": rows}


class RestartRequest(BaseModel):
    from_step: str = Field(description="A node id from /pipeline: steps before it are reused, it and those after run afresh.")
    company_ids: list[str] | None = Field(default=None, description="Only these companies; all of the run's when left out.")


@router.post("/runs/{run_id}/restart")
async def restart_run(
    run_id: str,
    req: RestartRequest,
    settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(get_run_store),
    decision_store: DecisionStore = Depends(get_decision_store),
    xbrl_source=Depends(get_xbrl_source),
) -> dict:
    """Starts the run again from one of its steps, as a new run with the
    same inputs and step settings. What comes before the step is reused
    from the document and LLM caches; the step and everything after it run
    afresh (see arp.extraction.steps.restart_overrides). From the rules
    step, the run itself is scored again instead -- nothing is extracted."""
    manifest = _manifest_or_404(run_store, run_id)
    if manifest.status in ("running", "pending"):
        raise HTTPException(409, "Stop the run first, or wait for it to finish.")
    if req.from_step == "rules":
        from arp.decision.templates import score_run

        if not score_run(run_store, run_id):
            raise HTTPException(400, "No Decision Studio framework is attached to this run.")
        return {"run_id": run_id, "run_type": manifest.run_type, "rescored": True}
    saved = _saved(run_store, run_id, "start_request.json")
    if saved is None:
        raise HTTPException(400, "This run was not started from the Extraction screen, so there is nothing to restart it from.")
    original = StartRequest.model_validate_json(saved)
    if req.from_step not in {n["id"] for n in pipeline_shape(original.profile, settings)["nodes"]}:
        raise HTTPException(400, f"`{req.from_step}` is not a step of the {original.profile} pipeline.")
    companies = original.companies or []
    if req.company_ids is not None:
        wanted = set(req.company_ids)
        companies = [c for c in companies if c.company_id in wanted]
        if not companies:
            raise HTTPException(400, "None of those companies are in this run.")

    overrides = restart_overrides(req.from_step)
    run_settings = (original.step_settings or StepSettings()).apply(settings).model_copy(update=overrides)
    registry = get_registry()
    if overrides.get("document_cache_enabled") is False:
        from arp.api.deps import build_registry
        from arp.storage.document_store import DocumentContentStore

        registry = build_registry(run_settings, DocumentContentStore(run_settings.document_store_dir, enabled=False))
    started = await _dispatch(
        original.model_copy(update={"companies": companies}), run_settings, run_store, registry, decision_store, xbrl_source
    )
    (run_store.run_dir(started["run_id"]) / "restarted_from.json").write_text(
        json.dumps({"run_id": run_id, "step": req.from_step, "company_count": len(companies)})
    )
    return started


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
    decisions = get_review_decisions(run_store, run_id)["decisions"]
    effective = effective_decisions(run_store, run_id, cosign_required={"edit"})
    return {"decisions": {k: {**d, "cosigned": k in effective} for k, d in decisions.items()}}


@router.get("/runs/{run_id}/review-history")
def get_extraction_review_history(
    run_id: str, item_key: str, run_store: RunStore = Depends(get_run_store)
) -> dict:
    return get_review_history(run_store, run_id, item_key)


@router.post("/runs/{run_id}/review")
def submit_extraction_review(
    run_id: str, req: ReviewDecisionRequest, run_store: RunStore = Depends(get_run_store),
    principal: Principal = Depends(current_user),
) -> dict:
    return submit_review(
        run_store, run_id, item_key=req.item_key, decision=req.decision, principal=principal,
        edited_value=req.edited_value, comment=req.comment,
    )


class CosignRequest(BaseModel):
    item_key: str


@router.post("/runs/{run_id}/cosign")
def cosign_extraction_review(
    run_id: str, req: CosignRequest, run_store: RunStore = Depends(get_run_store),
    principal: Principal = Depends(require_role("approver")),
) -> dict:
    try:
        record_cosign(run_store, run_id, req.item_key, principal)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"ok": True}
