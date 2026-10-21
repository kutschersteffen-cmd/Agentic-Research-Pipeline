from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from arp.api.auth import Principal, current_user
from arp.api.deps import get_llm_client, get_registry, get_run_store, get_taxonomy_store, settings_dep
from arp.api.review_endpoints import ReviewDecisionRequest, get_review_queue, submit_review
from arp.api.run_scheduling import schedule_llm_run
from arp.company_graph import CompanyGraphError
from arp.config import Settings
from arp.discovery.site_finder import DuckDuckGoSearchClient
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.factory import batch_settings
from arp.research.activity_generator import build_theme
from arp.research.exposure_layers import LayerSettingsError, load_run_layers, parse_as_of
from arp.research.indirect_exposure.factory import resolve_indirect_exposure_model
from arp.research.pipeline import create_theme_run, execute_theme_run
from arp.research.rd_exposure.resolver import RDResolverContext
from arp.research.revenue_exposure.catalogue import by_company as catalogue_by_company
from arp.research.revenue_exposure.catalogue import load_catalogue
from arp.research.revenue_exposure.resolver import RevenueResolverContext
from arp.schemas.common import CompanyRef
from arp.schemas.revenue_exposure import ActivityCatalogueMapping
from arp.schemas.thematic import ThemeDefinition
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore, ensure_taxonomy_usable_for_run
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
    batch: bool = Field(default=False, description="Run through the Message Batches API: 50% cheaper, slower.")
    theme: ThemeDefinition | None = None
    taxonomy_id: str | None = Field(default=None, description="Load a saved taxonomy instead of an inline theme.")
    taxonomy_version: int | None = Field(default=None, description="Defaults to the taxonomy's latest version.")
    companies: list[CompanyRef] | None = None
    universe_path: str | None = None
    use_sample_icio: bool = Field(
        default=False,
        description=(
            "Enable the indirect (input-output) exposure tier using the bundled illustrative ICIO-shaped sample "
            "dataset. For a real run, configure ARP_ICIO_MATRIX_PATH/ARP_ICIO_INDUSTRIES_PATH instead and leave "
            "this false. Mutually exclusive with use_sample_exiobase."
        ),
    )
    use_sample_exiobase: bool = Field(
        default=False,
        description=(
            "Enable the indirect (input-output) exposure tier using the bundled illustrative EXIOBASE-shaped "
            "sample dataset. For a real run, configure ARP_EXIOBASE_FLOWS_PATH/ARP_EXIOBASE_INDUSTRIES_PATH "
            "instead and leave this false. Mutually exclusive with use_sample_icio."
        ),
    )
    revenue_catalogue_path: str | None = Field(
        default=None, description="Server-side path to a structured revenue/capex catalogue CSV (see POST /api/revenue-catalogue/suggest-mapping)."
    )
    catalogue_mapping: list[ActivityCatalogueMapping] | None = Field(
        default=None, description="The reviewed activity->catalogue-label mapping. Required alongside revenue_catalogue_path."
    )
    enable_rd_exposure: bool = Field(
        default=False,
        description=(
            "Enable Method C (R&D-spend-intensity + news-mention scoring, arp/research/rd_exposure/) for "
            "activities whose lifecycle_stage is ideation or innovation -- a supplementary signal for "
            "pre-revenue themes where revenue-percentage scoring doesn't apply. Never short-circuits the "
            "qualitative debate. Off by default."
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
    settings = batch_settings(settings, req.batch)
    companies = req.companies or (load_company_universe(req.universe_path) if req.universe_path else None)
    if not companies:
        raise HTTPException(400, "Provide either `companies` or `universe_path`.")

    taxonomy = None
    if req.theme is not None:
        theme = req.theme
        # A theme loaded unedited from a saved taxonomy names it too: recorded for "used by" only, never re-checked.
        if req.taxonomy_id is not None:
            taxonomy = taxonomy_store.get(req.taxonomy_id, req.taxonomy_version)
    elif req.taxonomy_id is not None:
        taxonomy = taxonomy_store.get(req.taxonomy_id, req.taxonomy_version)
        if taxonomy is None:
            raise HTTPException(404, f"Taxonomy not found: {req.taxonomy_id}")
        try:
            ensure_taxonomy_usable_for_run(taxonomy, settings.require_ratified_taxonomy)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        theme = taxonomy.theme
    else:
        raise HTTPException(400, "Provide either `theme` or `taxonomy_id`.")

    if bool(req.revenue_catalogue_path) != bool(req.catalogue_mapping):
        raise HTTPException(400, "Provide both revenue_catalogue_path and catalogue_mapping together, or neither.")

    try:
        indirect_model = resolve_indirect_exposure_model(
            settings, use_sample_icio=req.use_sample_icio, use_sample_exiobase=req.use_sample_exiobase
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

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

    rd_resolver = None
    if req.enable_rd_exposure:
        rd_resolver = RDResolverContext(
            registry=registry,
            settings=settings,
            isic_model=indirect_model,
            search_client=DuckDuckGoSearchClient(settings.discovery_user_agent),
        )

    def _create() -> str:
        return create_theme_run(
            theme, companies, settings, run_store,
            universe_path=req.universe_path,
            use_sample_icio=req.use_sample_icio,
            use_sample_exiobase=req.use_sample_exiobase,
            revenue_catalogue_path=req.revenue_catalogue_path,
            catalogue_mapping=req.catalogue_mapping,
            enable_rd_exposure=req.enable_rd_exposure,
            taxonomy_id=taxonomy.taxonomy_id if taxonomy else None,
            taxonomy_version=taxonomy.version if taxonomy else None,
        )

    async def _run(run_id: str, llm, verifier_llm) -> None:
        await execute_theme_run(
            run_id,
            theme,
            companies,
            llm=llm,
            verifier_llm=verifier_llm,
            registry=registry,
            settings=settings,
            run_store=run_store,
            indirect_model=indirect_model,
            revenue_resolver=revenue_resolver,
            rd_resolver=rd_resolver,
        )

    run_id = schedule_llm_run(
        create_fn=_create, run=_run, settings=settings if req.batch else None, run_store=run_store
    )
    return {
        "run_id": run_id,
        "company_count": len(companies),
        "indirect_exposure_enabled": indirect_model is not None,
        "revenue_exposure_enabled": revenue_resolver is not None,
        "rd_exposure_enabled": rd_resolver is not None,
    }




@router.get("/runs/{run_id}/results")
def get_theme_results(
    run_id: str, offset: int = 0, limit: int = 200, run_store: RunStore = Depends(get_run_store)
) -> dict:
    rows = run_store.read_results(run_id)
    matches = [m for row in rows for m in row.get("company_matches", [])]
    return {"total": len(matches), "results": matches[offset : offset + limit]}


@router.get("/runs/{run_id}/review-queue")
def get_theme_review_queue(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    q = get_review_queue(run_store, run_id)  # sector codes live in the review workbench, with their reviewers hidden
    return {
        "pending": [r for r in q["pending"] if not r["item_key"].startswith("isic:")],
        "decided": [d for d in q["decided"] if not d["item"]["item_key"].startswith("isic:")],
    }


@router.post("/runs/{run_id}/review")
def submit_theme_review(
    run_id: str, req: ReviewDecisionRequest, run_store: RunStore = Depends(get_run_store),
    principal: Principal = Depends(current_user),
) -> dict:
    if req.item_key.startswith("isic:"):
        raise HTTPException(400, "decide sector codes through the review workbench")
    return submit_review(
        run_store, run_id, item_key=req.item_key, decision=req.decision, principal=principal,
        edited_value=req.edited_value, comment=req.comment,
    )


class LayerWeights(BaseModel):
    w1: float
    w2: float
    w3: float


class ThemeLayerRow(BaseModel):
    issuer_key: str
    name: str
    in_run: bool
    l1: float | None
    l2: float | None
    l3: float | None
    score: float | None
    pure_play: bool
    status: str
    rank: int | None
    l2_via: list[str] | None


class ThemeLayers(BaseModel):
    run_id: str
    as_of: date
    weights: LayerWeights
    decay: float
    max_hops: int
    pure_play_threshold: float
    rows: list[ThemeLayerRow]


def _r4(x: float | None) -> float | None:
    return None if x is None else round(x, 4)


@router.get("/runs/{run_id}/layers", response_model=ThemeLayers)
def get_theme_layers(
    run_id: str, as_of: str | None = None, run_store: RunStore = Depends(get_run_store),
) -> ThemeLayers:
    """Layer 1 (direct revenue share), Layer 2 (value chain, from the company graph's supply edges
    known at `as_of`), Layer 3 (no data yet) and score S per company; computed on read."""
    settings = Settings()  # the layer and graph settings as they are now, not as first cached
    try:
        day = parse_as_of(as_of)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        params, rows = load_run_layers(settings, run_store, run_id, day)
    except LookupError as exc:
        raise HTTPException(404, exc.args[0]) from exc
    except (LayerSettingsError, CompanyGraphError) as exc:
        raise HTTPException(503, str(exc)) from exc
    return ThemeLayers(
        run_id=run_id, as_of=day, weights=LayerWeights(w1=params.w1, w2=params.w2, w3=params.w3),
        decay=params.decay, max_hops=params.max_hops, pure_play_threshold=params.pure_play_threshold,
        rows=[ThemeLayerRow(**{**vars(r), "l1": _r4(r.l1), "l2": _r4(r.l2), "score": _r4(r.score)}) for r in rows],
    )
