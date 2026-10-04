from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from arp.api.auth import Principal, current_user
from arp.api.deps import get_document_content_store, get_run_store, settings_dep
from arp.config import Settings
from arp.review.context import build_context, item_source, read_snapshot
from arp.review.items import list_open_items
from arp.storage.document_store import DocumentContentStore
from arp.storage.run_store import RunStore
from arp.storage.safe_path import UnsafeIdentifierError

router = APIRouter(prefix="/api/review", tags=["review"])


@router.get("/items")
def list_review_items(
    run_id: str | None = None, run_store: RunStore = Depends(get_run_store), principal: Principal = Depends(current_user),
) -> dict:
    return {"items": list_open_items(run_store, principal, run_id=run_id)}


@router.get("/runs/{run_id}/items/{item_key}/context")
def get_item_context(
    run_id: str, item_key: str, run_store: RunStore = Depends(get_run_store), principal: Principal = Depends(current_user),
    settings: Settings = Depends(settings_dep), content_store: DocumentContentStore = Depends(get_document_content_store),
) -> dict:
    bundle = build_context(run_store, run_id, item_key, principal, settings=settings, content_store=content_store)
    if bundle is None:
        raise HTTPException(404, "Review item not found")
    return bundle


@router.get("/runs/{run_id}/items/{item_key}/source")
def get_item_source(
    run_id: str, item_key: str, doc_id: str, page: int = 1, run_store: RunStore = Depends(get_run_store),
    principal: Principal = Depends(current_user), content_store: DocumentContentStore = Depends(get_document_content_store),
) -> dict:
    source = item_source(run_store, run_id, item_key, doc_id, page, principal, content_store=content_store)
    if source is None:
        raise HTTPException(404, "Source page not found")
    return source


@router.get("/runs/{run_id}/snapshots/{snapshot_id}")
def get_snapshot(run_id: str, snapshot_id: str, run_store: RunStore = Depends(get_run_store)) -> Response:
    try:
        content = read_snapshot(run_store, run_id, snapshot_id)
    except UnsafeIdentifierError as exc:
        raise HTTPException(400, str(exc)) from None
    if content is None:
        raise HTTPException(404, "Snapshot not found")
    return Response(content=content, media_type="application/json")
