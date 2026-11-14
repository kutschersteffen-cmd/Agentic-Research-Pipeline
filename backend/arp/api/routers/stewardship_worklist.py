"""The stewardship priority worklist (spec `stewardship-priority-worklist`): rows, the weights preview, the
house engagement selection and the engagement programmes. Reads need `viewer`, changes `analyst` (the router-level `authorize`)."""

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
    Programme,
    ProgrammeCreate,
    ProgrammeDetail,
    ProgrammeList,
    ProgrammeMembersChange,
    ProgrammeSuggestions,
    SelectionChange,
    SelectionConfirm,
    SelectionList,
    Worklist,
)
from arp.stewardship import worklist
from arp.stewardship.policies import PolicyStore, validate_weights
from arp.stewardship.process import StreamStore, load_sample
from arp.stewardship.programmes import ProgrammeLog, UnknownProgramme
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
    try:
        validate_weights(body.content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    sample, records = load_sample(), engagements.list_all()
    rows = worklist.house_rows(streams.root, sample, records, today=datetime.now(UTC).date(), **_inputs(settings, sample))
    return worklist.preview(body.content, PolicyStore(streams.root).active(worklist.POLICY), rows)


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


def _names() -> dict[str, str]:
    return {i["issuer_id"]: i["name"] for i in load_sample()["issuers"]}


def _programme_call(fn, *args):
    try:
        return fn(*args)
    except UnknownProgramme as exc:
        raise HTTPException(404, f"unknown programme {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/programmes", response_model=ProgrammeList)
def get_programmes(streams: StreamStore = Depends(get_stream_store)) -> dict:
    """Every engagement programme with its member counts, the four built-in ones first."""
    return {"programmes": ProgrammeLog(streams.root).programmes()}


@router.post("/programmes", response_model=Programme)
def post_programme(
    body: ProgrammeCreate, streams: StreamStore = Depends(get_stream_store), principal: Principal = Depends(current_user)
) -> dict:
    """A new programme by name; its id is the name lower-cased with runs of other characters as `_`."""
    return _programme_call(ProgrammeLog(streams.root).create, body.name, principal.name)


@router.get("/programmes/{programme_id}", response_model=ProgrammeDetail)
def get_programme(programme_id: str, streams: StreamStore = Depends(get_stream_store)) -> dict:
    """The programme and every member it had, ended ones included."""
    return _programme_call(ProgrammeLog(streams.root).programme, programme_id)


@router.post("/programmes/{programme_id}/members", response_model=ProgrammeDetail)
def post_programme_members(
    programme_id: str,
    body: ProgrammeMembersChange,
    streams: StreamStore = Depends(get_stream_store),
    principal: Principal = Depends(current_user),
) -> dict:
    """Proposes companies, drops proposed ones and ends confirmed ones (with a reason)."""
    log = ProgrammeLog(streams.root)
    _programme_call(log.change, programme_id, _names(), body.add, body.remove, body.end, body.reason, principal.name)
    return log.programme(programme_id)


@router.post("/programmes/{programme_id}/confirm", response_model=Confirmed)
def post_programme_confirm(
    programme_id: str, streams: StreamStore = Depends(get_stream_store), principal: Principal = Depends(current_user)
) -> dict:
    """Every proposed member becomes confirmed, recorded as the signed-in user."""
    return {"confirmed": _programme_call(ProgrammeLog(streams.root).confirm, programme_id, principal.name)}


@router.get("/programmes/{programme_id}/suggestions", response_model=ProgrammeSuggestions)
def get_programme_suggestions(
    programme_id: str,
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    """Companies with an open or stalled issue on the programme's theme that are not members yet. Writes nothing."""
    return {
        "suggestions": _programme_call(ProgrammeLog(streams.root).suggestions, programme_id, _names(), engagements.list_all())
    }
