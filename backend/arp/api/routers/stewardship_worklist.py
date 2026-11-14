"""The stewardship priority worklist (spec `stewardship-priority-worklist`): rows, the weights preview and the
house engagement selection. Reads need `viewer`, changes `analyst` (the router-level `authorize`)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from arp.api.auth import Principal, current_user
from arp.api.deps import get_engagement_store, get_stream_store, settings_dep
from arp.config import Settings
from arp.db.session import require_dsn
from arp.schemas.worklist import (
    Confirmed,
    PriorityPreview,
    PriorityPreviewRequest,
    SelectionChange,
    SelectionConfirm,
    SelectionList,
    Worklist,
)
from arp.stewardship import worklist
from arp.stewardship.policies import PolicyStore
from arp.stewardship.process import StreamStore, load_sample
from arp.storage.engagement_store import EngagementStore
from arp.storage.portfolio_store_factory import build_portfolio_store

router = APIRouter(prefix="/api/stewardship", tags=["stewardship"])


def _inputs(settings: Settings, sample: dict) -> dict:
    ids = [i["issuer_id"] for i in sample["issuers"]]
    return {
        "meetings": worklist.last_meetings(require_dsn(settings)),
        "observations": worklist.latest_observations(build_portfolio_store(settings), ids),
    }


@router.get("/worklist", response_model=Worklist)
def get_worklist(
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    """One row per company of the house scope, computed from stored values on every request."""
    sample = load_sample()
    return worklist.build(streams.root, sample, engagements.list_all(), **_inputs(settings, sample))


@router.post("/studio/priority/preview", response_model=PriorityPreview)
def post_priority_preview(
    body: PriorityPreviewRequest,
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    """What candidate weights would change against the active version, on the house scope."""
    sample, records = load_sample(), engagements.list_all()
    rows = worklist.house_rows(streams.root, sample, records, today=datetime.now(UTC).date(), **_inputs(settings, sample))
    try:
        return worklist.preview(body.content, PolicyStore(streams.root).active(worklist.POLICY), rows)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _cycle(cycle: str | None) -> str:
    current = worklist.cycle_of(datetime.now(UTC).date())
    if cycle is not None and not worklist.CYCLE.fullmatch(cycle):
        raise HTTPException(422, f"A cycle looks like {current}")
    return cycle or current


@router.get("/selection", response_model=SelectionList)
def get_selection(cycle: str | None = None, streams: StreamStore = Depends(get_stream_store)) -> dict:
    """The house engagement selection of a cycle (default: the current one), folded from its log."""
    cycle = _cycle(cycle)
    in_scope = {i["issuer_id"] for i in load_sample()["issuers"]}
    rows = [{**r, "in_scope": r["issuer_id"] in in_scope} for r in worklist.SelectionLog(streams.root).rows(cycle)]
    return {"cycle": cycle, "current": cycle == worklist.cycle_of(datetime.now(UTC).date()), "rows": rows}


@router.post("/selection", response_model=SelectionList)
def post_selection(
    body: SelectionChange, streams: StreamStore = Depends(get_stream_store), principal: Principal = Depends(current_user)
) -> dict:
    """Adds companies as proposed and removes proposed ones; confirmed rows stay."""
    cycle = _cycle(body.cycle)
    names = {i["issuer_id"]: i["name"] for i in load_sample()["issuers"]}
    version = PolicyStore(streams.root).active_version(worklist.POLICY)
    try:
        worklist.SelectionLog(streams.root).change(cycle, datetime.now(UTC).date(), names, body.add, body.remove, principal.name, version)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return get_selection(cycle, streams)


@router.post("/selection/confirm", response_model=Confirmed)
def post_selection_confirm(
    body: SelectionConfirm, streams: StreamStore = Depends(get_stream_store), principal: Principal = Depends(current_user)
) -> dict:
    """Every proposed row of the cycle becomes confirmed, recorded as the signed-in user."""
    version = PolicyStore(streams.root).active_version(worklist.POLICY)
    try:
        n = worklist.SelectionLog(streams.root).confirm(_cycle(body.cycle), datetime.now(UTC).date(), principal.name, version)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"confirmed": n}
