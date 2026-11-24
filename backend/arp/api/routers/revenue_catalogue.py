from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arp.api.deps import get_llm_client, get_taxonomy_store, settings_dep
from arp.api.saved_universe import CATALOGUE_NOT_UPLOADED, saved_universe_file
from arp.config import Settings
from arp.research.revenue_exposure.catalogue import distinct_labels, load_catalogue
from arp.research.revenue_exposure.mapping import suggest_catalogue_mapping
from arp.schemas.revenue_exposure import ActivityCatalogueMapping
from arp.storage.taxonomy_store import TaxonomyStore

router = APIRouter(prefix="/api/revenue-catalogue", tags=["revenue-catalogue"])


class SuggestMappingRequest(BaseModel):
    taxonomy_id: str
    taxonomy_version: int | None = None
    catalogue_path: str


class SuggestMappingResponse(BaseModel):
    mappings: list[ActivityCatalogueMapping]


@router.post("/suggest-mapping", response_model=SuggestMappingResponse)
async def suggest_mapping(
    req: SuggestMappingRequest,
    store: TaxonomyStore = Depends(get_taxonomy_store),
    settings: Settings = Depends(settings_dep),
) -> SuggestMappingResponse:
    """Proposes which catalogue labels represent each taxonomy activity's
    revenue/capex -- a reviewable draft, never applied automatically. Pass
    the (edited, confirmed) result back as `catalogue_mapping` on
    POST /api/themes/runs alongside `revenue_catalogue_path`.
    """
    catalogue_path = saved_universe_file(req.catalogue_path, settings)
    if catalogue_path is None:
        raise HTTPException(400, CATALOGUE_NOT_UPLOADED)
    taxonomy = store.get(req.taxonomy_id, req.taxonomy_version)
    if taxonomy is None:
        raise HTTPException(404, f"Taxonomy not found: {req.taxonomy_id}")

    catalogue = load_catalogue(catalogue_path)

    labels_by_metric = {"revenue": distinct_labels(catalogue, "revenue"), "capex": distinct_labels(catalogue, "capex")}
    llm = get_llm_client()
    mappings, _usage = await suggest_catalogue_mapping(taxonomy.theme, labels_by_metric, llm)
    return SuggestMappingResponse(mappings=mappings)
