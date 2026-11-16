from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from arp.api.deps import get_document_content_store, get_run_store, settings_dep
from arp.config import Settings
from arp.storage.document_store import DocumentContentStore
from arp.storage.run_store import RunStore
from arp.walkthrough.view import build_walkthrough

router = APIRouter(prefix="/api/walkthrough", tags=["walkthrough"])


@router.get("/runs/{run_id}/companies/{company_id}")
def get_walkthrough(
    run_id: str, company_id: str, item: str, period_end: str | None = None, basis: str | None = None,
    run_store: RunStore = Depends(get_run_store), settings: Settings = Depends(settings_dep),
    content_store: DocumentContentStore = Depends(get_document_content_store),
) -> dict:
    try:
        return build_walkthrough(run_store, content_store, settings, run_id=run_id, company_id=company_id, item=item,
                                 period_end=period_end, basis=basis)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
