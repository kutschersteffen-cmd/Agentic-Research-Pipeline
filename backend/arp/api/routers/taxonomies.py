from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from arp.api.deps import get_llm_client, get_registry, get_taxonomy_store, settings_dep
from arp.config import Settings
from arp.discovery.site_finder import DuckDuckGoSearchClient
from arp.ingestion.registry import DocumentSourceRegistry
from arp.research.activity_generator import build_theme, build_theme_industry_anchored
from arp.research.indirect_exposure.factory import build_leontief_model
from arp.research.taxonomy_sources.authority import build_theme_from_authority_sources
from arp.research.taxonomy_sources.discovery import discover_authority_sources, discover_thematic_funds
from arp.research.taxonomy_sources.empirical import build_theme_empirical
from arp.research.taxonomy_sources.etf_holdings import build_theme_from_holdings
from arp.research.taxonomy_sources.news_mining import build_theme_from_news_and_transcripts
from arp.schemas.common import CompanyRef
from arp.schemas.taxonomy import DerivationMethod, Taxonomy
from arp.schemas.taxonomy_sources import SourceCandidate
from arp.schemas.thematic import ThemeDefinition
from arp.storage.taxonomy_store import TaxonomyStore
from arp.universe import load_company_universe

router = APIRouter(prefix="/api/taxonomies", tags=["taxonomies"])


class DiscoverSourcesRequest(BaseModel):
    name: str


class DiscoverSourcesResponse(BaseModel):
    authority_sources: list[SourceCandidate]
    thematic_funds: list[SourceCandidate]


@router.post("/discover-sources", response_model=DiscoverSourcesResponse)
async def discover_sources(req: DiscoverSourcesRequest, settings: Settings = Depends(settings_dep)) -> DiscoverSourcesResponse:
    """The research step: web-searches for candidate authority sources
    (official taxonomies, standards bodies) and existing thematic ETFs/
    indices, for the user to review and select from before running a
    derivation. Nothing here is fetched or used automatically.
    """
    search_client = DuckDuckGoSearchClient(settings.discovery_user_agent)
    authority = await discover_authority_sources(req.name, search_client)
    funds = await discover_thematic_funds(req.name, search_client)
    return DiscoverSourcesResponse(authority_sources=authority, thematic_funds=funds)


class CreateTaxonomyRequest(BaseModel):
    name: str
    description: str = ""
    derivation_method: DerivationMethod = DerivationMethod.LLM_DRAFT

    # industry_anchored
    use_sample_icio: bool = False

    # authority_source -- URLs the user selected from /discover-sources
    authority_urls: list[str] = Field(default_factory=list)

    # empirical / news_transcript_mining
    companies: list[CompanyRef] | None = None
    universe_path: str | None = None
    sample_size: int = 25

    # news_transcript_mining
    mine_news: bool = True

    # etf_index_holdings -- a path from /api/universe/upload (any CSV works)
    holdings_path: str | None = None


@router.post("", response_model=Taxonomy)
async def create_taxonomy(
    req: CreateTaxonomyRequest,
    settings: Settings = Depends(settings_dep),
    store: TaxonomyStore = Depends(get_taxonomy_store),
    registry: DocumentSourceRegistry = Depends(get_registry),
) -> Taxonomy:
    """Drafts and saves a new taxonomy (v1) using the selected
    derivation_method -- persisted as a reusable, versioned artifact
    instead of a one-off run parameter. See docs/METHODOLOGY.md for what
    each method needs and when it's the right choice.
    """
    method = req.derivation_method

    # Validate each method's required inputs before touching the LLM client,
    # so a malformed request gets a precise 400 even if no API key is
    # configured yet -- an unrelated 503 shouldn't mask a real input error.
    model = None
    if method == DerivationMethod.INDUSTRY_ANCHORED:
        model = build_leontief_model(settings, use_sample=req.use_sample_icio)
        if model is None:
            raise HTTPException(400, "No ICIO data available: configure ARP_ICIO_MATRIX_PATH/ARP_ICIO_INDUSTRIES_PATH or set use_sample_icio.")
    elif method == DerivationMethod.AUTHORITY_SOURCE and not req.authority_urls:
        raise HTTPException(400, "Provide authority_urls (see POST /api/taxonomies/discover-sources).")
    elif method == DerivationMethod.ETF_INDEX_HOLDINGS and not req.holdings_path:
        raise HTTPException(400, "Provide holdings_path (upload via POST /api/universe/upload, then pass its path).")

    companies = req.companies or (load_company_universe(req.universe_path) if req.universe_path else None)
    if method == DerivationMethod.EMPIRICAL and not companies:
        raise HTTPException(400, "Provide `companies` or `universe_path` for derivation_method=empirical.")

    llm = get_llm_client()

    if method == DerivationMethod.LLM_DRAFT:
        theme, _usage = await build_theme(req.name, req.description, llm)
        notes = "Freeform LLM draft, no industry anchor."

    elif method == DerivationMethod.INDUSTRY_ANCHORED:
        theme, _usage = await build_theme_industry_anchored(req.name, req.description, model.industry_reference_list(), llm)
        notes = f"Anchored against {model.edition_label} ({len(model.codes)} industries)."

    elif method == DerivationMethod.AUTHORITY_SOURCE:
        try:
            theme, notes, _usage = await build_theme_from_authority_sources(
                req.name, req.description, req.authority_urls, llm, settings.discovery_user_agent
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    elif method == DerivationMethod.EMPIRICAL:
        try:
            theme, notes, _usage = await build_theme_empirical(
                req.name, req.description, companies, registry, llm, settings, req.sample_size
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    elif method == DerivationMethod.NEWS_TRANSCRIPT_MINING:
        search_client = DuckDuckGoSearchClient(settings.discovery_user_agent) if req.mine_news else None
        try:
            theme, notes, _usage = await build_theme_from_news_and_transcripts(
                req.name, req.description, llm,
                search_client=search_client,
                companies=companies,
                registry=registry if companies else None,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    elif method == DerivationMethod.ETF_INDEX_HOLDINGS:
        if not req.holdings_path:
            raise HTTPException(400, "Provide holdings_path (upload via POST /api/universe/upload, then pass its path).")
        try:
            theme, notes, _usage = await build_theme_from_holdings(req.name, req.description, Path(req.holdings_path), llm)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    else:
        raise HTTPException(400, f"derivation_method={method.value} has nothing to draft; use POST .../versions to save a hand-written theme.")

    return store.create(req.name, theme, method, notes)


@router.get("")
def list_taxonomies(store: TaxonomyStore = Depends(get_taxonomy_store)) -> dict:
    return {"taxonomies": [t.model_dump(mode="json") for t in store.list_all()]}


@router.get("/{taxonomy_id}", response_model=Taxonomy)
def get_taxonomy(
    taxonomy_id: str, version: int | None = None, store: TaxonomyStore = Depends(get_taxonomy_store)
) -> Taxonomy:
    taxonomy = store.get(taxonomy_id, version)
    if taxonomy is None:
        raise HTTPException(404, "Taxonomy not found")
    return taxonomy


@router.get("/{taxonomy_id}/versions")
def list_taxonomy_versions(taxonomy_id: str, store: TaxonomyStore = Depends(get_taxonomy_store)) -> dict:
    return {"versions": [t.model_dump(mode="json") for t in store.list_versions(taxonomy_id)]}


class NewVersionRequest(BaseModel):
    theme: ThemeDefinition
    source_notes: str = "Manual edit."


@router.post("/{taxonomy_id}/versions", response_model=Taxonomy)
def new_taxonomy_version(
    taxonomy_id: str, req: NewVersionRequest, store: TaxonomyStore = Depends(get_taxonomy_store)
) -> Taxonomy:
    try:
        return store.new_version(taxonomy_id, req.theme, DerivationMethod.MANUAL, req.source_notes)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


class RatifyRequest(BaseModel):
    version: int
    ratified_by: str


@router.post("/{taxonomy_id}/ratify", response_model=Taxonomy)
def ratify_taxonomy(
    taxonomy_id: str, req: RatifyRequest, store: TaxonomyStore = Depends(get_taxonomy_store)
) -> Taxonomy:
    try:
        return store.ratify(taxonomy_id, req.version, req.ratified_by)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
