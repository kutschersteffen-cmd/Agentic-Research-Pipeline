from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arp.api.deps import get_llm_client, get_taxonomy_store, settings_dep
from arp.config import Settings
from arp.research.activity_generator import build_theme, build_theme_industry_anchored
from arp.research.indirect_exposure.factory import build_leontief_model
from arp.schemas.taxonomy import DerivationMethod, Taxonomy
from arp.schemas.thematic import ThemeDefinition
from arp.storage.taxonomy_store import TaxonomyStore

router = APIRouter(prefix="/api/taxonomies", tags=["taxonomies"])


class CreateTaxonomyRequest(BaseModel):
    name: str
    description: str = ""
    use_sample_icio: bool = False


@router.post("", response_model=Taxonomy)
async def create_taxonomy(
    req: CreateTaxonomyRequest,
    settings: Settings = Depends(settings_dep),
    store: TaxonomyStore = Depends(get_taxonomy_store),
) -> Taxonomy:
    """Drafts and saves a new taxonomy (v1). `use_sample_icio` anchors the
    draft against the bundled illustrative ISIC reference list so
    activities come with an initial core_isic_codes guess; otherwise it's
    a freeform LLM draft, same as /api/themes/decompose but persisted as a
    reusable, versioned artifact instead of a one-off run parameter.
    """
    llm = get_llm_client()
    if req.use_sample_icio:
        model = build_leontief_model(settings, use_sample=True)
        assert model is not None
        theme, _usage = await build_theme_industry_anchored(
            req.name, req.description, model.industry_reference_list(), llm
        )
        method = DerivationMethod.INDUSTRY_ANCHORED
        notes = f"Anchored against {model.edition_label} ({len(model.codes)} industries)."
    else:
        theme, _usage = await build_theme(req.name, req.description, llm)
        method = DerivationMethod.LLM_DRAFT
        notes = "Freeform LLM draft, no industry anchor."
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
