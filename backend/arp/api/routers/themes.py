from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from arp.api.deps import get_llm_client, get_registry, get_run_store, get_taxonomy_store, settings_dep
from arp.config import Settings
from arp.ingestion.registry import DocumentSourceRegistry
from arp.orchestration.review_queue import latest_decisions, record_review_decision
from arp.research.activity_generator import build_theme
from arp.research.indirect_exposure.factory import build_leontief_model
from arp.research.pipeline import create_theme_run, execute_theme_run, resume_theme_run
from arp.research.revenue_exposure.catalogue import by_company as catalogue_by_company, load_catalogue
from arp.research.revenue_exposure.resolver import RevenueResolverContext
from arp.schemas.common import CompanyRef
from arp.schemas.revenue_exposure import ActivityCatalogueMapping
from arp.schemas.thematic import ThemeDefinition
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore
from arp.universe import load_company_universe

router = APIRouter(prefix="/api/themes", tags=["themes"])


class DecomposeRequest(BaseModel):
    name: str
    description: str = ""


@router.post("/decompose", response_model=ThemeDefinition)
async def decompose_theme(req: DecomposeRequest) -> ThemeDefinition:
    """Drafts a ThemeDefinition (MECE activities with in/out-of-scope text)
    for the user to review and edit before any run uses it."""
    llm = get_llm_client()
    theme, _usage = await build_theme(req.name, req.description, llm)
    return theme


class RunRequest(BaseModel):
    theme: ThemeDefinition | None = None
    taxonomy_id: str | None = Field(default=None, description="Load a saved taxonomy instead of an inline theme.")
    taxonomy_version: int | None = Field(default=None, description="Defaults to the taxonomy's latest version.")
    companies: list[CompanyRef] | None = None
    universe_path: str | None = None
    use_sample_icio: bool = Field(
        default=False,
        description=(
            "Enable the indirect (input-output) exposure tier using the bundled illustrative sample dataset. "
            "For a real run, configure ARP_ICIO_MATRIX_PATH/ARP_ICIO_INDUSTRIES_PATH instead and leave this false."
        ),
    )
    revenue_catalogue_path: str | None = Field(
        default=None, description="Server-side path to a structured revenue/capex catalogue CSV (see POST /api/revenue-catalogue/suggest-mapping)."
    )
    catalogue_mapping: list[ActivityCatalogueMapping] | None = Field(
        default=None, description="The reviewed activity->catalogue-label mapping. Required alongside revenue_catalogue_path."
    )


@router.post("/runs")
async def start_theme_run(
    req: RunRequest,
    settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(get_run_store),
    registry: DocumentSourceRegistry = Depends(get_registry),
    taxonomy_store: TaxonomyStore = Depends(get_taxonomy_store),
) -> dict:
    companies = req.companies or (load_company_universe(req.universe_path) if req.universe_path else None)
    if not companies:
        raise HTTPException(400, "Provide either `companies` or `universe_path`.")

    if req.theme is not None:
        theme = req.theme
    elif req.taxonomy_id is not None:
        taxonomy = taxonomy_store.get(req.taxonomy_id, req.taxonomy_version)
        if taxonomy is None:
            raise HTTPException(404, f"Taxonomy not found: {req.taxonomy_id}")
        theme = taxonomy.theme
    else:
        raise HTTPException(400, "Provide either `theme` or `taxonomy_id`.")

    if bool(req.revenue_catalogue_path) != bool(req.catalogue_mapping):
        raise HTTPException(400, "Provide both revenue_catalogue_path and catalogue_mapping together, or neither.")

    llm = get_llm_client()  # raises a clear 4xx-worthy error before a run manifest is even created
    run_id = create_theme_run(
        theme, companies, settings, run_store,
        universe_path=req.universe_path,
        use_sample_icio=req.use_sample_icio,
        revenue_catalogue_path=req.revenue_catalogue_path,
        catalogue_mapping=req.catalogue_mapping,
    )
    indirect_model = build_leontief_model(settings, use_sample=req.use_sample_icio)

    revenue_resolver = None
    if req.revenue_catalogue_path:
        catalogue = load_catalogue(Path(req.revenue_catalogue_path))
        revenue_resolver = RevenueResolverContext(
            catalogue_by_company=catalogue_by_company(catalogue),
            mappings=req.catalogue_mapping or [],
            registry=registry,
            settings=settings,
            isic_model=indirect_model,
        )

    async def _background() -> None:
        await execute_theme_run(
            run_id,
            theme,
            companies,
            llm=llm,
            registry=registry,
            settings=settings,
            run_store=run_store,
            indirect_model=indirect_model,
            revenue_resolver=revenue_resolver,
        )

    asyncio.create_task(_background())
    return {
        "run_id": run_id,
        "company_count": len(companies),
        "indirect_exposure_enabled": indirect_model is not None,
        "revenue_exposure_enabled": revenue_resolver is not None,
    }


@router.get("/runs/{run_id}")
def get_theme_run(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    return manifest.model_dump(mode="json")


@router.post("/runs/{run_id}/resume")
async def resume_theme_run_endpoint(
    run_id: str,
    settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(get_run_store),
    registry: DocumentSourceRegistry = Depends(get_registry),
) -> dict:
    """Re-invokes execute_theme_run for a run that was interrupted, failed,
    partially completed, or cancelled -- reconstructed from what
    create_theme_run persisted (theme.json, universe_path,
    catalogue_mapping.json). Already-completed companies are skipped
    automatically (run_batch's own resumability); nothing is redone.
    """
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    if manifest.run_type != "theme":
        raise HTTPException(400, f"Run {run_id} is a {manifest.run_type} run, not a theme run.")
    if manifest.status == "completed":
        raise HTTPException(400, "This run already completed successfully -- nothing to resume.")
    if not manifest.params.get("universe_path"):
        raise HTTPException(400, "This run has no stored universe_path (it predates resume support, or was started with inline `companies`) and can't be reconstructed.")

    llm = get_llm_client()  # surfaces a clean 503 before we schedule anything if unconfigured

    async def _background() -> None:
        await resume_theme_run(run_id, llm=llm, registry=registry, settings=settings, run_store=run_store)

    asyncio.create_task(_background())
    return {"run_id": run_id, "status": "resumed"}


@router.get("/runs/{run_id}/results")
def get_theme_results(
    run_id: str, offset: int = 0, limit: int = 200, run_store: RunStore = Depends(get_run_store)
) -> dict:
    rows = run_store.read_jsonl(run_store.results_path(run_id))
    matches = [m for row in rows for m in row.get("company_matches", [])]
    return {"total": len(matches), "results": matches[offset : offset + limit]}


@router.get("/runs/{run_id}/review-queue")
def get_theme_review_queue(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    rows = run_store.read_jsonl(run_store.review_queue_path(run_id))
    decisions = latest_decisions(run_store, run_id)
    pending = [r for r in rows if r["item_key"] not in decisions]
    return {"pending": pending, "decided": [{"item": r, "decision": decisions[r["item_key"]]} for r in rows if r["item_key"] in decisions]}


class ReviewDecisionRequest(BaseModel):
    item_key: str
    decision: str  # approve | edit | reject
    reviewer: str | None = None
    edited_value: dict | None = None


@router.post("/runs/{run_id}/review")
def submit_theme_review(
    run_id: str, req: ReviewDecisionRequest, run_store: RunStore = Depends(get_run_store)
) -> dict:
    record_review_decision(run_store, run_id, req.item_key, req.decision, req.reviewer, req.edited_value)
    return {"status": "recorded"}
