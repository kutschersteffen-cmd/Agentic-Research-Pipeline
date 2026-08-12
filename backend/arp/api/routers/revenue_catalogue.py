from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arp.api.deps import get_llm_client, get_taxonomy_store
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
async def suggest_mapping(req: SuggestMappingRequest, store: TaxonomyStore = Depends(get_taxonomy_store)) -> SuggestMappingResponse:
    """Proposes which catalogue labels represent each taxonomy activity's
    revenue/capex -- a reviewable draft, never applied automatically. Pass
    the (edited, confirmed) result back as `catalogue_mapping` on
    POST /api/themes/runs alongside `revenue_catalogue_path`.
    """
    taxonomy = store.get(req.taxonomy_id, req.taxonomy_version)
    if taxonomy is None:
        raise HTTPException(404, f"Taxonomy not found: {req.taxonomy_id}")

    catalogue_path = Path(req.catalogue_path)
    if not catalogue_path.exists():
        raise HTTPException(404, f"Catalogue file not found: {req.catalogue_path}")
    catalogue = load_catalogue(catalogue_path)

    labels_by_metric = {"revenue": distinct_labels(catalogue, "revenue"), "capex": distinct_labels(catalogue, "capex")}
    llm = get_llm_client()
    mappings, _usage = await suggest_catalogue_mapping(taxonomy.theme, labels_by_metric, llm)
    return SuggestMappingResponse(mappings=mappings)
