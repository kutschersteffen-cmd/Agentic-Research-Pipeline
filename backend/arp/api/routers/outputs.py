"""The output catalog (Data Hub · Outputs, and the shared input picker): every stored output in one shape, with what
uses it. Read-only; see arp/catalog.py."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from arp import catalog
from arp.api.deps import get_decision_store, get_index_store, get_reporting_store, get_run_store, get_taxonomy_store, settings_dep
from arp.config import Settings

router = APIRouter(prefix="/api/outputs", tags=["outputs"])


@router.get("")
def list_outputs(
    kind: str | None = None, settings: Settings = Depends(settings_dep), run_store=Depends(get_run_store),
    decisions=Depends(get_decision_store), taxonomy=Depends(get_taxonomy_store), index=Depends(get_index_store),
    reports=Depends(get_reporting_store),
) -> dict:
    if kind is not None and kind not in catalog.KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(catalog.KINDS)}")
    return {"outputs": catalog.catalog(runs_dir=settings.runs_dir, run_store=run_store, decisions=decisions, taxonomy=taxonomy,
                                       index=index, reports=reports, kind=kind)}
