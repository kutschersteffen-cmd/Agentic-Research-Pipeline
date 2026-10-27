"""Dossier step 5: the theme's position and its stewardship standards (arp/themes/position.py)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from arp.api.auth import Principal, require_role
from arp.api.deps import (
    get_extraction_starter,
    get_llm_client,
    get_run_store,
    get_stream_store,
    get_taxonomy_store,
    resolve,
    settings_dep,
)
from arp.api.routers.dossier_research import _dossier
from arp.config import Settings
from arp.db.fields import SchemaRegistry, released_fields
from arp.db.session import require_dsn
from arp.schemas.common import JobStatus, now_iso
from arp.stewardship.process import StreamStore
from arp.stewardship.trigger_store import TriggerStore
from arp.themes.dossiers import Dossier, DossierStore, exposed_companies, get_dossier_store
from arp.themes.position import (
    POLICY,
    PositionApproval,
    PositionDraft,
    PositionStore,
    PositionVersion,
    StandardsDraft,
    build_standards_content,
    check_standards,
    current_facts,
    get_position_store,
    note_items,
    position_problem,
    released_theme_fields,
    schema_id_for,
    schema_to_extract,
    standards_store,
    standards_triggers,
    standards_view,
)
from arp.themes.research import ResearchStore, get_research_store

router = APIRouter(prefix="/api/dossiers/{dossier_id}", tags=["dossiers"])
_approver = require_role("approver")


class Instructions(BaseModel):
    instructions: str | None = None


class VersionRef(BaseModel):
    version: int


class PositionView(BaseModel):
    versions: list[PositionVersion]
    approvals: list[PositionApproval]
    approved_version: int | None


class StandardsSaved(BaseModel):
    version: int


class Activation(BaseModel):
    version: int
    approved_by: str
    approved_at: str
    path: str
    extraction_run_id: str | None


class CheckResult(BaseModel):
    company_id: str
    name: str
    standard_id: str
    value: bool | int | float | str | None
    period_end: str | None
    result: str


class StandardsCheck(BaseModel):
    checked_at: str
    results: list[CheckResult]
    flagged: int


class StandardsView(BaseModel):
    versions: list[dict]
    activations: list[dict]
    active_version: int
    active: dict
    latest_check: StandardsCheck | None
    field_names: dict[str, str]  # field_id -> name, for every field a version's criteria use


# --- position ---

_POSITION_SYSTEM = """\
You write the house position on an investment theme for a stewardship team: a short summary, then paragraphs that \
together form a comprehensive, neutral narrative of what the theme means for the companies exposed to it. Use ONLY \
the research note's items given (risks and opportunities). Every paragraph cites, by item_id, the items it rests on, \
and every item is cited by at least one paragraph. No item ids other than those given. When a previous version and \
instructions are given, redraft that version following the instructions."""


def _note_or_409(research: ResearchStore, dossier_id: str):
    record = research.get(dossier_id)
    if record.approved_round is None:
        raise HTTPException(409, "research note not approved")
    return record


@router.get("/position", response_model=PositionView)
def get_position(dossier_id: str, dossiers: DossierStore = Depends(get_dossier_store),
                 positions: PositionStore = Depends(get_position_store)) -> PositionView:
    _dossier(dossier_id, dossiers, write=False)
    approvals = positions.approvals(dossier_id)
    return PositionView(versions=positions.versions(dossier_id), approvals=approvals,
                        approved_version=approvals[-1].version if approvals else None)


@router.post("/position/draft", response_model=PositionVersion)
async def draft_position(dossier_id: str, req: Instructions, request: Request,
                         dossiers: DossierStore = Depends(get_dossier_store),
                         research: ResearchStore = Depends(get_research_store),
                         positions: PositionStore = Depends(get_position_store)) -> PositionVersion:
    _dossier(dossier_id, dossiers, write=True)
    record = _note_or_409(research, dossier_id)
    items = note_items(record)
    listing = "\n".join(f"- {i.item_id} ({i.kind}): {i.title}. {i.summary}" for i in items)
    prompt = f"Research note items:\n{listing}"
    instructions = (req.instructions or "").strip() or None
    if versions := positions.versions(dossier_id):
        latest = versions[-1]
        paragraphs = "\n\n".join(f"{n}. {p.text} [cites: {', '.join(p.cites)}]" for n, p in enumerate(latest.paragraphs, 1))
        prompt += f"\n\nLatest version (v{latest.version}):\nSummary: {latest.summary}\n\n{paragraphs}"
        prompt += f"\n\nInstructions: {instructions or '(none)'}"
    draft, _ = await resolve(request, get_llm_client).complete_structured(
        system=_POSITION_SYSTEM, prompt=prompt, output_model=PositionDraft)
    if problem := position_problem(draft.paragraphs, [i.item_id for i in items]):
        raise HTTPException(502, f"position draft invalid: {problem}")
    return positions.add(dossier_id, draft, note_version=record.approved_round, created_by="model", path="model_draft",
                         instructions=instructions)


@router.post("/position/versions", response_model=PositionVersion)
def edit_position(dossier_id: str, req: PositionDraft, principal: Principal = Depends(_approver),
                  dossiers: DossierStore = Depends(get_dossier_store),
                  research: ResearchStore = Depends(get_research_store),
                  positions: PositionStore = Depends(get_position_store)) -> PositionVersion:
    _dossier(dossier_id, dossiers, write=True)
    record = _note_or_409(research, dossier_id)
    if problem := position_problem(req.paragraphs, [i.item_id for i in note_items(record)]):
        raise HTTPException(422, problem)
    return positions.add(dossier_id, req, note_version=record.approved_round, created_by=principal.user_id,
                         path="owner_edit", instructions=None)


@router.post("/position/approve", response_model=PositionApproval)
def approve_position(dossier_id: str, req: VersionRef, principal: Principal = Depends(_approver),
                     dossiers: DossierStore = Depends(get_dossier_store),
                     research: ResearchStore = Depends(get_research_store),
                     positions: PositionStore = Depends(get_position_store)) -> PositionApproval:
    _dossier(dossier_id, dossiers, write=True)
    versions = positions.versions(dossier_id)
    if not versions:
        raise HTTPException(404, f"unknown position version {req.version}")
    latest = versions[-1]
    if req.version != latest.version:
        raise HTTPException(409, f"only the latest version can be approved (v{latest.version})")
    note = research.get(dossier_id).approved_round
    if latest.note_version != note:
        raise HTTPException(409, f"position v{latest.version} rests on note v{latest.note_version}; v{note} is approved")
    return positions.approve(dossier_id, latest.version, principal.user_id)


# --- standards ---

_STANDARDS_SYSTEM = """\
You derive stewardship standards from a house position on an investment theme: what the house expects of the \
companies exposed to it. Every standard needs a clear definition and ONE criterion on ONE data point that is easy to \
identify in company reports: a comparison (>=, <=, >, <, ==) on a number, percentage or currency amount (value in the \
field's canonical unit), `==` true/false on a boolean, or `==` one of an enum's allowed values. Never a criterion a \
person has to judge. Ids are S1..Sn in order. `rests_on` lists the position paragraph numbers (1-based) the standard \
rests on. Use an existing released field (`data: "existing"`) whenever one fits; otherwise define the data point in \
`new_fields` (with clear extraction instructions) and use it with `data: "new"`. Every new field must be used. When a \
previous version and instructions are given, redraft that version following the instructions."""


def _approved_position(positions: PositionStore, dossier_id: str) -> PositionVersion:
    approved = positions.approved(dossier_id)
    if approved is None:
        raise HTTPException(409, "position not approved")
    return approved


def _save_standards(dossier: Dossier, draft: StandardsDraft, *, position: PositionVersion, path: str, created_by: str,
                    note: str, dsn: str, streams: StreamStore) -> int:
    """Raises ValueError with the validator's message when the version is not admissible."""
    released = released_fields(dsn)
    # a carried field retired since its release is dropped, so the standards that used it can be removed
    carried = [f for f in released_theme_fields(SchemaRegistry(dsn), schema_id_for(dossier.dossier_id)) if f.field_id in released]
    content = build_standards_content(draft, dossier_id=dossier.dossier_id, dossier_name=dossier.name,
                                      position_version=position.version, path=path, carried=carried)
    sample = {"paragraphs": len(position.paragraphs), "released": released, "carried": {f.field_id for f in carried}}
    return standards_store(streams.root, dossier.dossier_id).save(POLICY, content, note, created_by, sample)


@router.get("/standards", response_model=StandardsView)
def get_standards(dossier_id: str, settings: Settings = Depends(settings_dep), dossiers: DossierStore = Depends(get_dossier_store),
                  positions: PositionStore = Depends(get_position_store),
                  streams: StreamStore = Depends(get_stream_store)) -> StandardsView:
    _dossier(dossier_id, dossiers, write=False)
    view = standards_view(standards_store(streams.root, dossier_id))
    names = {f["field_id"]: f["name"] for v in view["versions"] for f in (v.get("schema") or {}).get("fields", [])}
    if settings.postgres_dsn:  # reading needs no database; without one, existing fields show by id
        names |= {fid: f["name"] for fid, f in released_fields(settings.postgres_dsn).items()}
    return StandardsView(**view, latest_check=positions.latest_check(dossier_id), field_names=names)


@router.post("/standards/draft", response_model=StandardsSaved)
async def draft_standards(dossier_id: str, req: Instructions, request: Request,
                          settings: Settings = Depends(settings_dep), dossiers: DossierStore = Depends(get_dossier_store),
                          positions: PositionStore = Depends(get_position_store),
                          streams: StreamStore = Depends(get_stream_store)) -> StandardsSaved:
    dsn = require_dsn(settings)
    dossier = _dossier(dossier_id, dossiers, write=True)
    position = _approved_position(positions, dossier_id)
    store = standards_store(streams.root, dossier_id)
    fields = released_fields(dsn)
    listing = "\n".join(
        f"- {f['field_id']}: {f['name']} ({f['data_type']}{', unit ' + f['unit'] if f['unit'] else ''}"
        f"{', allowed ' + ', '.join(f['allowed_values']) if f['allowed_values'] else ''}). {f['description']}"
        for f in fields.values())
    paragraphs = "\n\n".join(f"{n}. {p.text}" for n, p in enumerate(position.paragraphs, 1))
    prompt = (f"Theme: {dossier.name}\n\nApproved position (v{position.version}):\nSummary: {position.summary}\n\n{paragraphs}"
              f"\n\nReleased fields:\n{listing or '(none)'}")
    if (latest := max(v["version"] for v in store.versions(POLICY))) > 0:
        # a field the last activation released is existing data now, whatever the version said when it was saved
        shown = [{**x, "data": "existing"} if x["field_id"] in fields else x for x in store.content(POLICY, latest)["standards"]]
        prompt += f"\n\nLatest standards version (v{latest}):\n{shown}"
    instructions = (req.instructions or "").strip()
    prompt += f"\n\nInstructions: {instructions or '(none)'}"
    draft, _ = await resolve(request, get_llm_client).complete_structured(
        system=_STANDARDS_SYSTEM, prompt=prompt, output_model=StandardsDraft)
    try:
        version = _save_standards(dossier, draft, position=position, path="model_draft", created_by="model",
                                  note=instructions, dsn=dsn, streams=streams)
    except ValueError as exc:
        raise HTTPException(502, f"standards draft invalid: {exc}") from exc
    return StandardsSaved(version=version)


@router.post("/standards/versions", response_model=StandardsSaved)
def edit_standards(dossier_id: str, req: StandardsDraft, principal: Principal = Depends(_approver),
                   settings: Settings = Depends(settings_dep), dossiers: DossierStore = Depends(get_dossier_store),
                   positions: PositionStore = Depends(get_position_store),
                   streams: StreamStore = Depends(get_stream_store)) -> StandardsSaved:
    dsn = require_dsn(settings)
    dossier = _dossier(dossier_id, dossiers, write=True)
    position = _approved_position(positions, dossier_id)
    try:
        version = _save_standards(dossier, req, position=position, path="owner_edit", created_by=principal.user_id,
                                  note="", dsn=dsn, streams=streams)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return StandardsSaved(version=version)


@router.post("/standards/activate", response_model=Activation)
async def activate_standards(
    dossier_id: str, req: VersionRef, request: Request, principal: Principal = Depends(_approver),
    settings: Settings = Depends(settings_dep), dossiers: DossierStore = Depends(get_dossier_store),
    positions: PositionStore = Depends(get_position_store), streams: StreamStore = Depends(get_stream_store),
    start_extraction: Callable = Depends(get_extraction_starter),
) -> Activation:
    dsn = require_dsn(settings)
    dossier = _dossier(dossier_id, dossiers, write=True)
    store = standards_store(streams.root, dossier_id)
    if req.version <= 0 or req.version not in {v["version"] for v in store.versions(POLICY)}:
        raise HTTPException(404, f"unknown standards version {req.version}")
    content = store.content(POLICY, req.version)
    approved = positions.approved(dossier_id)
    if approved is None or content["position_version"] != approved.version:
        raise HTTPException(409, f"standards v{req.version} rest on position v{content['position_version']}; "
                                 f"v{approved.version if approved else None} is approved")
    run_store = resolve(request, get_run_store)
    companies = exposed_companies(dossier, run_store, resolve(request, get_taxonomy_store))
    if companies is None:
        raise HTTPException(409, "find companies first")
    run_id = None
    if content["schema"] is not None:
        schema = schema_to_extract(SchemaRegistry(dsn), content["schema"], principal.user_id)
        ref = f"{schema.schema_id}:v{schema.version}"
        # trial runs don't count; a failed or cancelled one doesn't either, so activating again retries (owner, 2026-10-26)
        live = [r for r in run_store.extraction_runs() if r.status not in (JobStatus.FAILED, JobStatus.CANCELLED)]
        if not any(r.params.get("schema_version") == ref for r in live):
            try:
                run_id = start_extraction(schema, companies, settings)
            except Exception as exc:  # noqa: BLE001 - any failure to start is answered, and nothing is activated
                raise HTTPException(502, f"extraction could not start: {exc}") from exc
    try:
        row = store.activate(POLICY, req.version, principal.user_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Activation(**row, extraction_run_id=run_id)


@router.post("/standards/check", response_model=StandardsCheck)
def check_companies(dossier_id: str, request: Request, settings: Settings = Depends(settings_dep),
                    dossiers: DossierStore = Depends(get_dossier_store),
                    positions: PositionStore = Depends(get_position_store),
                    streams: StreamStore = Depends(get_stream_store)) -> StandardsCheck:
    dsn = require_dsn(settings)
    dossier = _dossier(dossier_id, dossiers, write=True)
    store = standards_store(streams.root, dossier_id)
    if store.active_version(POLICY) == 0:
        raise HTTPException(409, "no active standards")
    companies = exposed_companies(dossier, resolve(request, get_run_store), resolve(request, get_taxonomy_store))
    if companies is None:
        raise HTTPException(409, "find companies first")
    standards = store.active(POLICY)["standards"]
    facts = current_facts(dsn, [c.entity_id for c in companies if c.entity_id], [s["field_id"] for s in standards])
    results = check_standards(companies, standards, facts)
    check = {"checked_at": now_iso(), "results": results,
             "flagged": len({r["company_id"] for r in results if r["result"] == "unmet"})}
    if triggers := standards_triggers(results, standards, companies, dossier_id=dossier_id, theme=dossier.name):
        TriggerStore(streams.root).record_standards(dossier_id, check["checked_at"], triggers)
    positions.save_check(dossier_id, check)
    return StandardsCheck(**check)

