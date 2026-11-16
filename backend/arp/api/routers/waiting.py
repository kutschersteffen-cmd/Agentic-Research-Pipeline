from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from arp.api.auth import Principal, current_user
from arp.api.deps import get_engagement_store, get_run_store, get_stream_store, settings_dep
from arp.config import Settings
from arp.review.waiting import WaitingCounts, waiting_counts
from arp.stewardship.process import HOUSE, StreamStore, flow
from arp.storage.run_store import RunStore

router = APIRouter(prefix="/api", tags=["review"])


# shortcut: flow() and list_open_items run per request; cache when this endpoint takes more than 300 ms.
@router.get("/waiting")
def get_waiting(
    run_store: RunStore = Depends(get_run_store),
    principal: Principal = Depends(current_user),
    streams: StreamStore = Depends(get_stream_store),
    engagements=Depends(get_engagement_store),
    settings: Settings = Depends(settings_dep),
) -> WaitingCounts:
    try:
        house = flow(HOUSE, streams, engagements.list_all(), settings.engagement_sla_days)
    except Exception as exc:  # a broken policy file: counting decisions as 0 would be a guess
        raise HTTPException(503, "Stewardship decisions could not be counted") from exc
    return waiting_counts(run_store, principal, house)
