"""Dossier step 3: propose and approve sources, write and approve the note (arp/themes/research.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, field_validator

from arp.api.auth import Principal, current_user
from arp.api.deps import get_run_store, get_taxonomy_store, settings_dep
from arp.api.run_scheduling import schedule_llm_run
from arp.config import Settings
from arp.discovery.site_finder import build_web_search_client
from arp.llm.base import LLMClient
from arp.orchestration.job_manager import JobManager
from arp.schemas.common import now_iso
from arp.schemas.taxonomy import Taxonomy, TaxonomyStatus
from arp.storage.run_store import RunStore
from arp.storage.safe_path import UnsafeIdentifierError, safe_filename
from arp.storage.taxonomy_store import TaxonomyStore
from arp.themes.dossiers import Dossier, DossierStore, get_dossier_store
from arp.themes.research import (
    UPLOAD_SUFFIXES,
    Category,
    Refused,
    ResearchRecord,
    ResearchRound,
    ResearchSource,
    ResearchStore,
    SourceFile,
    get_research_store,
    merge_proposals,
    open_round,
    propose_sources,
    read_sources,
    start_note,
    start_proposal,
    write_note,
    written_note,
)

router = APIRouter(prefix="/api/dossiers/{dossier_id}/research", tags=["dossiers"])


class ResearchView(BaseModel):
    dossier_id: str
    approved_round: int | None
    rounds: list[ResearchRound]


class SourceCreate(BaseModel):
    title: str
    publisher: str
    url: str
    category: Category
    why: str
    how: str

    @field_validator("title", "publisher", "url", "why", "how")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class NoteReject(BaseModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("a reason is required")
        return v.strip()


class RunStarted(BaseModel):
    run_id: str


class ProposalStarted(RunStarted):
    round: int


def _dossier(dossier_id: str, store: DossierStore, *, write: bool) -> Dossier:
    dossier = store.get(dossier_id)
    if dossier is None:
        raise HTTPException(404, f"unknown dossier '{dossier_id}'")
    if write and dossier.status == "shelved":
        raise HTTPException(409, "dossier is shelved")
    return dossier


def _ratified(dossier: Dossier, taxonomy_store: TaxonomyStore) -> Taxonomy:
    versions = taxonomy_store.list_versions(dossier.taxonomy_id) if dossier.taxonomy_id else []
    ratified = [t for t in versions if t.status == TaxonomyStatus.RATIFIED]
    if not ratified:
        raise HTTPException(409, "ratify a taxonomy first")
    return ratified[-1]


def _apply(store: ResearchStore, dossier_id: str, fn):
    try:
        return store.update(dossier_id, fn)
    except Refused as exc:
        raise HTTPException(exc.status, str(exc)) from exc


def _check(store: ResearchStore, dossier_id: str, fn) -> None:
    """Runs a transition on a copy, so a refusal answers before the LLM client is built; nothing is saved."""
    try:
        fn(store.get(dossier_id))
    except Refused as exc:
        raise HTTPException(exc.status, str(exc)) from exc


def _view(record: ResearchRecord) -> ResearchView:
    return ResearchView(dossier_id=record.dossier_id, approved_round=record.approved_round, rounds=record.rounds)


def _source(r: ResearchRound, source_id: str) -> ResearchSource:
    source = next((s for s in r.sources if s.source_id == source_id), None)
    if source is None:
        raise Refused(404, f"unknown source '{source_id}'")
    return source


@router.get("", response_model=ResearchView)
def get_research(dossier_id: str, dossiers: DossierStore = Depends(get_dossier_store),
                 store: ResearchStore = Depends(get_research_store)) -> ResearchView:
    _dossier(dossier_id, dossiers, write=False)
    return _view(store.get(dossier_id))


@router.post("/propose", status_code=202, response_model=ProposalStarted)
async def propose(
    dossier_id: str, settings: Settings = Depends(settings_dep), dossiers: DossierStore = Depends(get_dossier_store),
    store: ResearchStore = Depends(get_research_store), taxonomy_store: TaxonomyStore = Depends(get_taxonomy_store),
    run_store: RunStore = Depends(get_run_store), principal: Principal = Depends(current_user),
) -> ProposalStarted:
    taxonomy = _ratified(_dossier(dossier_id, dossiers, write=True), taxonomy_store)
    _check(store, dossier_id, lambda rec: start_proposal(rec, taxonomy.version, ""))
    started: dict[str, int] = {}

    def create() -> str:
        def fn(record: ResearchRecord) -> str:
            start_proposal(record, taxonomy.version, "")  # again under the lock, before any run manifest exists
            run_id = JobManager(run_store).create_run(
                "theme_research_sources", {"dossier_id": dossier_id, "taxonomy_id": taxonomy.taxonomy_id}, 0).run_id
            record.latest.proposal_run_id = run_id
            started["round"] = record.latest.round
            return run_id
        return _apply(store, dossier_id, fn)

    async def run(run_id: str, llm: LLMClient, _verifier: LLMClient) -> None:
        proposed, error = None, None
        try:
            proposed = await propose_sources(taxonomy, build_web_search_client(settings.discovery_user_agent), llm)
        except Exception as exc:  # noqa: BLE001 - recorded on the round and the run
            error = f"{type(exc).__name__}: {exc}"

        def finish(record: ResearchRecord) -> None:
            r = record.latest
            if r is None or r.proposal_run_id != run_id:
                return
            if proposed is None:
                r.plan_status = "proposal_failed"
            else:
                merge_proposals(r, proposed)

        store.update(dossier_id, finish)
        JobManager(run_store).finish_run(run_id, error=error)

    run_id = schedule_llm_run(create_fn=create, run=run, run_store=run_store, started_by=principal)
    return ProposalStarted(run_id=run_id, round=started["round"])


@router.post("/sources", response_model=ResearchSource)
def add_source(
    dossier_id: str, req: SourceCreate, dossiers: DossierStore = Depends(get_dossier_store),
    store: ResearchStore = Depends(get_research_store), principal: Principal = Depends(current_user),
) -> ResearchSource:
    _dossier(dossier_id, dossiers, write=True)
    source = ResearchSource(**req.model_dump(), added_by=principal.name)
    _apply(store, dossier_id, lambda rec: open_round(rec).sources.append(source))
    return source


@router.delete("/sources/{source_id}")
def delete_source(dossier_id: str, source_id: str, dossiers: DossierStore = Depends(get_dossier_store),
                  store: ResearchStore = Depends(get_research_store)) -> dict:
    _dossier(dossier_id, dossiers, write=True)

    def fn(record: ResearchRecord) -> None:
        r = open_round(record)
        r.sources.remove(_source(r, source_id))

    _apply(store, dossier_id, fn)
    return {"deleted": source_id}


@router.post("/sources/{source_id}/file", response_model=ResearchSource)
async def upload_source_file(
    dossier_id: str, source_id: str, file: UploadFile, settings: Settings = Depends(settings_dep),
    dossiers: DossierStore = Depends(get_dossier_store), store: ResearchStore = Depends(get_research_store),
    principal: Principal = Depends(current_user),
) -> ResearchSource:
    _dossier(dossier_id, dossiers, write=True)

    def check(record: ResearchRecord) -> ResearchSource:
        r = record.latest
        if r is None:
            raise Refused(404, f"unknown source '{source_id}'")
        source = _source(r, source_id)
        if r.note and r.note.status not in ("write_failed", "rejected"):
            raise Refused(409, "the note is already written")
        return source

    _apply(store, dossier_id, check)
    try:
        filename = safe_filename(file.filename)
    except UnsafeIdentifierError as exc:
        raise HTTPException(415, "upload a PDF, HTML or plain-text file") from exc
    if not filename.lower().endswith(UPLOAD_SUFFIXES):
        raise HTTPException(415, "upload a PDF, HTML or plain-text file")
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"File is larger than the {settings.max_upload_bytes // 1_000_000} MB upload limit.")

    def save(record: ResearchRecord) -> ResearchSource:
        source = check(record)  # again under the lock: the note may have started meanwhile
        store.save_file(dossier_id, source_id, filename, data)
        source.file = SourceFile(filename=filename, uploaded_by=principal.name, uploaded_at=now_iso())
        return source

    return _apply(store, dossier_id, save)


@router.post("/plan/approve", response_model=ResearchRound)
def approve_plan(dossier_id: str, dossiers: DossierStore = Depends(get_dossier_store),
                 store: ResearchStore = Depends(get_research_store), principal: Principal = Depends(current_user)) -> ResearchRound:
    _dossier(dossier_id, dossiers, write=True)

    def fn(record: ResearchRecord) -> ResearchRound:
        r = open_round(record)
        if not r.sources:
            raise Refused(409, "add at least one source")
        r.plan_status, r.plan_approved_by, r.plan_approved_at = "approved", principal.name, now_iso()
        return r

    return _apply(store, dossier_id, fn)


@router.post("/note", status_code=202, response_model=RunStarted)
async def start_writing(
    dossier_id: str, settings: Settings = Depends(settings_dep), dossiers: DossierStore = Depends(get_dossier_store),
    store: ResearchStore = Depends(get_research_store), taxonomy_store: TaxonomyStore = Depends(get_taxonomy_store),
    run_store: RunStore = Depends(get_run_store), principal: Principal = Depends(current_user),
) -> RunStarted:
    dossier = _dossier(dossier_id, dossiers, write=True)
    _check(store, dossier_id, lambda rec: start_note(rec, ""))
    taxonomy = _ratified(dossier, taxonomy_store)

    def create() -> str:
        def fn(record: ResearchRecord) -> str:
            start_note(record, "")
            run_id = JobManager(run_store).create_run("theme_research_note", {"dossier_id": dossier_id}, 0).run_id
            record.latest.note_run_id = run_id
            return run_id
        return _apply(store, dossier_id, fn)

    async def run(run_id: str, llm: LLMClient, _verifier: LLMClient) -> None:
        record = store.get(dossier_id)
        r = record.latest
        error, unread = None, []
        try:
            docs, unread = await read_sources([(s, store.file_path(dossier_id, s)) for s in r.sources],
                                              settings.discovery_user_agent)
            if not docs:
                error = "no approved source could be read"
            else:
                sections, dropped = await write_note(taxonomy, docs, llm)
        except Exception as exc:  # noqa: BLE001 - recorded on the note and the run
            error = f"{type(exc).__name__}: {exc}"

        def finish(rec: ResearchRecord) -> None:
            note = rec.latest.note if rec.latest and rec.latest.note_run_id == run_id else None
            if note is None:
                return
            if error:
                note.status, note.error = "write_failed", error
            else:
                note.status, note.sections, note.dropped_items, note.written_at = "written", sections, dropped, now_iso()
            note.unread_sources = unread

        store.update(dossier_id, finish)
        JobManager(run_store).finish_run(run_id, error=error)

    run_id = schedule_llm_run(create_fn=create, run=run, run_store=run_store, started_by=principal)
    return RunStarted(run_id=run_id)


@router.post("/note/approve", response_model=ResearchRound)
def approve_note(dossier_id: str, dossiers: DossierStore = Depends(get_dossier_store),
                 store: ResearchStore = Depends(get_research_store), principal: Principal = Depends(current_user)) -> ResearchRound:
    _dossier(dossier_id, dossiers, write=True)

    def fn(record: ResearchRecord) -> ResearchRound:
        r = written_note(record)
        r.note.status, r.note.approved_by, r.note.approved_at = "approved", principal.name, now_iso()
        return r

    return _apply(store, dossier_id, fn)


@router.post("/note/reject", response_model=ResearchRound)
def reject_note(dossier_id: str, req: NoteReject, dossiers: DossierStore = Depends(get_dossier_store),
                store: ResearchStore = Depends(get_research_store), principal: Principal = Depends(current_user)) -> ResearchRound:
    _dossier(dossier_id, dossiers, write=True)

    def fn(record: ResearchRecord) -> ResearchRound:
        r = written_note(record)
        r.note.status, r.note.rejected_by, r.note.rejected_at, r.note.reject_reason = "rejected", principal.name, now_iso(), req.reason
        r.plan_status = "proposed"
        return r

    return _apply(store, dossier_id, fn)
