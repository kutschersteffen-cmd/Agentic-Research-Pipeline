"""The stewardship priority worklist (spec `stewardship-priority-worklist`): rows per scope, the weights preview,
the engagement selection per scope, the engagement programmes, notes per company and the vote ledger per company. Reads need `viewer`, changes `analyst` (the router-level `authorize`)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from arp.api.auth import Principal, current_user
from arp.api.deps import get_engagement_store, get_stream_store, settings_dep
from arp.config import Settings
from arp.db.session import require_dsn
from arp.schemas.worklist import (
    Confirmed,
    Note,
    NoteCreate,
    NoteList,
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
    VoteList,
    Worklist,
    WorklistScopes,
)
from arp.stewardship import worklist
from arp.stewardship.notes import NoteLog
from arp.stewardship.policies import PolicyStore, validate_weights
from arp.stewardship.process import StreamStore, house_universe, load_sample
from arp.stewardship.programmes import ProgrammeLog, UnknownProgramme
from arp.storage.engagement_store import EngagementStore
from arp.storage.portfolio_store_factory import build_portfolio_store

router = APIRouter(prefix="/api/stewardship", tags=["stewardship"])


def _inputs(settings: Settings, sample: dict, store=None) -> dict:
    ids = [i["issuer_id"] for i in sample["issuers"]]
    return {
        "meetings": worklist.last_meetings(require_dsn(settings)),
        "observations": worklist.latest_observations(store or build_portfolio_store(settings), ids),
    }


def _scope(key: str, sample: dict, store) -> dict:
    try:
        return worklist.resolve_scope(key, sample, store)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _funds(sample: dict, store) -> dict:
    return worklist.fund_holdings(store) if worklist.has_funds(sample) else {}


def _in_scope(key: str, sample: dict, settings: Settings) -> set[str]:
    """The scope's company ids (404 or 422 like the worklist)."""
    if key == "house":
        return {i["issuer_id"] for i in sample["issuers"]}
    store = build_portfolio_store(settings)
    return {i["issuer_id"] for i in worklist.scope_issuers(sample, _scope(key, sample, store), _funds(sample, store))}


@router.get("/worklist", response_model=Worklist)
def get_worklist(
    scope: str = "house",
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    """One row per company of the scope (house, `portfolio:<id>` or `group:<id>`), computed from stored values on every request."""
    sample, store = load_sample(), build_portfolio_store(settings)
    resolved = _scope(scope, sample, store)
    return worklist.build(
        streams.root, sample, engagements.list_all(), scope=resolved, funds=_funds(sample, store),
        labels=worklist.scope_labels(store), **_inputs(settings, sample, store),
    )  # fmt: skip


@router.get("/worklist/scopes", response_model=WorklistScopes)
def get_worklist_scopes(settings: Settings = Depends(settings_dep)) -> dict:
    """The house, every fund with company holdings at the latest snapshot, and every group of funds or companies."""
    sample, store = house_universe(), build_portfolio_store(settings)
    return {"scopes": worklist.scopes(sample, store, _funds(sample, store))}


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
def get_selection(
    cycle: str | None = None,
    scope: str = "house",
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
) -> dict:
    """The engagement selection of a scope and cycle (default: the current one), folded from its log."""
    cycle = _cycle(cycle)
    return _selection(cycle, scope, _in_scope(scope, house_universe(), settings), streams)


def _selection(cycle: str, scope: str, in_scope: set[str], streams: StreamStore) -> dict:
    rows = [{**r, "in_scope": r["issuer_id"] in in_scope} for r in worklist.SelectionLog(streams.root).rows(cycle, scope)]
    return {"cycle": cycle, "current": cycle == worklist.cycle_of(datetime.now(UTC).date()), "rows": rows}


@router.post("/selection", response_model=SelectionList)
def post_selection(
    body: SelectionChange,
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
    principal: Principal = Depends(current_user),
) -> dict:
    """Adds companies of the scope as proposed and removes proposed ones; confirmed rows stay."""
    cycle, sample = _cycle(body.cycle), house_universe()
    names = {i["issuer_id"]: i["name"] for i in sample["issuers"]}
    in_scope = _in_scope(body.scope, sample, settings)
    version = PolicyStore(streams.root).active_version(worklist.POLICY)
    try:
        worklist.SelectionLog(streams.root).change(
            cycle, datetime.now(UTC).date(), names, body.add, body.remove, principal.name, version, body.scope, in_scope
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _selection(cycle, body.scope, in_scope, streams)


@router.post("/selection/confirm", response_model=Confirmed)
def post_selection_confirm(
    body: SelectionConfirm,
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
    principal: Principal = Depends(current_user),
) -> dict:
    """Every proposed row of the scope and cycle becomes confirmed, recorded as the signed-in user."""
    _in_scope(body.scope, house_universe(), settings)  # 404 or 422 like the worklist
    version = PolicyStore(streams.root).active_version(worklist.POLICY)
    try:
        n = worklist.SelectionLog(streams.root).confirm(_cycle(body.cycle), datetime.now(UTC).date(), principal.name, version, body.scope)
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


@router.post("/notes", response_model=Note)
def post_note(
    body: NoteCreate,
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
    principal: Principal = Depends(current_user),
) -> dict:
    """Adds a note on a company of the house universe; `scope` only records where it was written."""
    sample = house_universe()
    _in_scope(body.scope, sample, settings)
    if body.company_id not in {i["issuer_id"] for i in sample["issuers"]}:
        raise HTTPException(422, "unknown company")
    try:
        return NoteLog(streams.root).add(body.company_id, body.text, principal.name, body.scope)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/notes", response_model=NoteList)
def get_notes(company_id: str, streams: StreamStore = Depends(get_stream_store)) -> dict:
    """The company's notes, newest first. No route edits or deletes a note."""
    return {"notes": NoteLog(streams.root).notes(company_id)}


@router.get("/votes", response_model=VoteList)
def get_votes(company_id: str, settings: Settings = Depends(settings_dep)) -> dict:
    """The company's vote-ledger decisions, newest meeting first (at most 500, with the total)."""
    return worklist.votes(require_dsn(settings), company_id)
