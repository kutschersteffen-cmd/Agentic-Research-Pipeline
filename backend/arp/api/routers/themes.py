from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from arp.api.deps import get_llm_client, get_registry, get_run_store, get_taxonomy_store, settings_dep
from arp.config import Settings
from arp.ingestion.registry import DocumentSourceRegistry
from arp.orchestration.review_queue import latest_decisions, record_review_decision
from arp.research.activity_generator import build_theme
from arp.research.indirect_exposure.factory import build_leontief_model
from arp.research.pipeline import create_theme_run, execute_theme_run
from arp.schemas.common import CompanyRef
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

    run_id = create_theme_run(theme, companies, settings, run_store)
    llm = get_llm_client()  # raises a clear 4xx-worthy error before we schedule anything if unconfigured
    indirect_model = build_leontief_model(settings, use_sample=req.use_sample_icio)

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
        )

    asyncio.create_task(_background())
    return {"run_id": run_id, "company_count": len(companies), "indirect_exposure_enabled": indirect_model is not None}


@router.get("/runs/{run_id}")
def get_theme_run(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    return manifest.model_dump(mode="json")


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
