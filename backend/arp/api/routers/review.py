from __future__ import annotations

from fastapi import APIRouter, Depends

from arp.api.auth import Principal, current_user
from arp.api.deps import get_run_store
from arp.review.items import list_open_items
from arp.storage.run_store import RunStore

router = APIRouter(prefix="/api/review", tags=["review"])


@router.get("/items")
def list_review_items(
    run_id: str | None = None, run_store: RunStore = Depends(get_run_store), principal: Principal = Depends(current_user),
) -> dict:
    return {"items": list_open_items(run_store, principal, run_id=run_id)}
