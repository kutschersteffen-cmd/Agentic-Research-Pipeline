from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from arp.api.auth import Principal, current_user, require_role
from arp.api.deps import get_document_content_store, get_run_store, settings_dep
from arp.checks.effectiveness import effectiveness
from arp.config import Settings
from arp.review.analytics import MONTH_PATTERN, monthly_totals
from arp.review.context import build_context, item_source, read_snapshot
from arp.review.decide import DecisionError, decide
from arp.review.items import list_open_items
from arp.review.quality import reviewer_stats
from arp.schemas.review import ItemDecisionRequest
from arp.storage.document_store import DocumentContentStore
from arp.storage.run_store import RunStore
from arp.storage.safe_path import UnsafeIdentifierError

router = APIRouter(prefix="/api/review", tags=["review"])


@router.get("/items")
def list_review_items(
    run_id: str | None = None, run_store: RunStore = Depends(get_run_store), principal: Principal = Depends(current_user),
) -> dict:
    return {"items": list_open_items(run_store, principal, run_id=run_id)}


@router.get("/check-effectiveness", dependencies=[Depends(require_role("approver"))])
def get_check_effectiveness(run_store: RunStore = Depends(get_run_store)) -> dict:
    return {"checks": [asdict(s) for s in effectiveness(run_store)]}


@router.get("/quality", dependencies=[Depends(require_role("approver"))])
def get_reviewer_quality(run_store: RunStore = Depends(get_run_store), settings: Settings = Depends(settings_dep)) -> dict:
    return {"reviewers": [asdict(s) for s in reviewer_stats(run_store, settings)]}


@router.get("/analytics", dependencies=[Depends(require_role("approver"))])
def get_review_analytics(month: str = Query(pattern=MONTH_PATTERN), run_store: RunStore = Depends(get_run_store)) -> dict:
    return {"month": month, "totals": [asdict(t) for t in monthly_totals(run_store, month)]}


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


@router.post("/runs/{run_id}/items/{item_key}/decision")
def post_item_decision(
    run_id: str, item_key: str, req: ItemDecisionRequest, run_store: RunStore = Depends(get_run_store),
    principal: Principal = Depends(current_user), settings: Settings = Depends(settings_dep),
    content_store: DocumentContentStore = Depends(get_document_content_store),
) -> dict:
    try:
        return decide(run_store, run_id, item_key, req, principal, settings=settings, content_store=content_store)
    except DecisionError as exc:
        raise HTTPException(exc.status, exc.message) from None


@router.get("/runs/{run_id}/snapshots/{snapshot_id}")
def get_snapshot(run_id: str, snapshot_id: str, run_store: RunStore = Depends(get_run_store)) -> Response:
    try:
        content = read_snapshot(run_store, run_id, snapshot_id)
    except UnsafeIdentifierError as exc:
        raise HTTPException(400, str(exc)) from None
    if content is None:
        raise HTTPException(404, "Snapshot not found")
    return Response(content=content, media_type="application/json")
