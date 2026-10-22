from __future__ import annotations

import hashlib
from datetime import date
from pathlib import PurePath
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select

from arp.api.auth import Principal, current_user, require_role
from arp.api.deps import blob_store_dep, get_llm_client, get_run_store, settings_dep
from arp.api.run_scheduling import schedule_llm_run
from arp.db import models as m
from arp.db.session import transaction
from arp.orchestration.job_manager import JobManager
from arp.orchestration.jobs import RunBusy, run_lease
from arp.rfp import store
from arp.rfp.draft import APPROVED, DRAFTED, EDITED, LEFT_BLANK, flags_for
from arp.rfp.fill import FillRefused, fill
from arp.rfp.locations import SUFFIXES
from arp.rfp.text import has_figures, plus_12_months
from arp.schemas.rfp import (
    RfpAnswerIn,
    RfpApproveIn,
    RfpAssigneeIn,
    RfpLibraryEntryEdit,
    RfpLibraryEntryOut,
    RfpLibraryImportOut,
    RfpProjectOut,
    RfpProjectSummary,
)
from arp.storage.document_blob_store import upload_or_fail

router = APIRouter(prefix="/api/rfp", tags=["rfp"])
_approver = require_role("approver")
_MEDIA = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _suffix(name: str | None) -> str:
    suffix = PurePath(name or "").suffix.lower()
    if suffix not in SUFFIXES:
        raise HTTPException(400, f"{name or 'The file'} is not a .docx or .xlsx file.")
    return suffix


def _entry(s, entry_id: int) -> m.RfpLibraryEntry:
    e = s.get(m.RfpLibraryEntry, entry_id)
    if e is None:
        raise HTTPException(404, "Library entry not found")
    return e


def _project(s, project_id: int) -> m.RfpProject:
    p = s.get(m.RfpProject, project_id)
    if p is None:
        raise HTTPException(404, "RFP project not found")
    return p


def _question(s, project_id: int, qid: int, lock: bool = False) -> m.RfpQuestion:
    q = s.get(m.RfpQuestion, qid, with_for_update=lock)
    if q is None or q.project_id != project_id:
        raise HTTPException(404, "Question not found")
    return q


# --- library -----------------------------------------------------------------------------------


@router.get("/library", response_model=list[RfpLibraryEntryOut])
def list_library() -> list[RfpLibraryEntryOut]:
    with transaction() as s:
        return [store.entry_out(e) for e in s.scalars(select(m.RfpLibraryEntry).order_by(m.RfpLibraryEntry.id))]


@router.post("/library/import", response_model=RfpLibraryImportOut, dependencies=[Depends(_approver)])
async def import_library(files: list[UploadFile] = File(...), llm=Depends(get_llm_client)) -> RfpLibraryImportOut:
    loaded = []
    for f in files:
        _suffix(f.filename)
        loaded.append((PurePath(f.filename).name, await f.read()))
    imported, dropped = await store.import_library(loaded, llm)
    return RfpLibraryImportOut(imported=imported, dropped=dropped)


@router.put("/library/{entry_id}", response_model=RfpLibraryEntryOut, dependencies=[Depends(_approver)])
def edit_library_entry(entry_id: int, body: RfpLibraryEntryEdit) -> RfpLibraryEntryOut:
    with transaction() as s:
        e = _entry(s, entry_id)
        for name, value in body.model_dump(exclude_unset=True).items():
            if value is not None or name == "owner":
                setattr(e, name, value)
        e.has_figures = has_figures(e.answer)
        return store.entry_out(e)


@router.post("/library/{entry_id}/retire", response_model=RfpLibraryEntryOut, dependencies=[Depends(_approver)])
def retire_library_entry(entry_id: int) -> RfpLibraryEntryOut:
    with transaction() as s:
        e = _entry(s, entry_id)
        e.status = "retired"
        return store.entry_out(e)


# --- projects ----------------------------------------------------------------------------------


@router.get("/projects", response_model=list[RfpProjectSummary])
def list_projects() -> list[RfpProjectSummary]:
    with transaction() as s:
        return store.project_summaries(s)


@router.post("/projects", response_model=RfpProjectOut)
async def create_project(
    file: UploadFile = File(...),
    investor: str = Form(..., min_length=1),
    due_date: date | None = Form(None),
    user: Principal = Depends(current_user),
    blobs=Depends(blob_store_dep),
    settings=Depends(settings_dep),
    run_store=Depends(get_run_store),
) -> RfpProjectOut:
    """Stores the investor's file unchanged and starts finding and auto-filling its questions in the background."""
    suffix = _suffix(file.filename)
    data = await file.read()
    key = hashlib.sha256(data).hexdigest()
    upload_or_fail(blobs, key, data)
    created: dict[str, int] = {}

    def create() -> str:  # called once both model clients resolved, so a missing key leaves no project behind
        run_id = JobManager(run_store).create_run("rfp", {}, 0).run_id
        with transaction() as s:
            p = m.RfpProject(investor=investor, due_date=due_date, filename=PurePath(file.filename).name, content_key=key,
                             run_id=run_id, run_status="detecting", created_by=user.user_id)
            s.add(p)
            s.flush()
            created["id"] = p.id
        return run_id

    async def run(run_id, llm, _verifier) -> None:
        await store.detect_and_fill(created["id"], data, suffix, llm, settings)
        JobManager(run_store).finish_run(run_id)

    schedule_llm_run(create_fn=create, run=run)
    return get_project(created["id"])


@router.get("/projects/{project_id}", response_model=RfpProjectOut)
def get_project(project_id: int) -> RfpProjectOut:
    with transaction() as s:
        return store.project_out(s, _project(s, project_id))


def _run_alive(run_store, run_id: str | None) -> bool:
    """A worker holds the run's lease. A process restart frees it, so a run left `detecting` or `drafting` by a
    restart can be started again."""
    if not run_id:
        return False
    try:
        with run_lease(run_store, run_id):
            return False
    except RunBusy:
        return True


@router.post("/projects/{project_id}/autofill", response_model=RfpProjectOut)
async def autofill_project(
    project_id: int, settings=Depends(settings_dep), run_store=Depends(get_run_store), blobs=Depends(blob_store_dep)
) -> RfpProjectOut:
    """Drafts every `no source` question again, e.g. after the library has grown. A project with no questions yet
    (its detection failed) finds them first."""
    with transaction() as s:
        p = _project(s, project_id)
        if p.run_status in ("detecting", "drafting") and _run_alive(run_store, p.run_id):
            raise HTTPException(409, "This RFP is still being processed.")
        redetect = not store.questions_of(s, project_id)
        filename, key = p.filename, p.content_key
    data = blobs.get(key) if redetect else b""

    def create() -> str:
        run_id = JobManager(run_store).create_run("rfp", {"project_id": project_id}, 0).run_id
        store.set_run_status(project_id, "detecting" if redetect else "drafting", run_id=run_id)
        return run_id

    async def run(run_id, llm, _verifier) -> None:
        if redetect:
            await store.detect_and_fill(project_id, data, _suffix(filename), llm, settings)
        else:
            try:
                await store.autofill(project_id, llm, settings)
                store.set_run_status(project_id, "done")
            except Exception:
                store.set_run_status(project_id, "failed")
                raise
        JobManager(run_store).finish_run(run_id)

    schedule_llm_run(create_fn=create, run=run)
    return get_project(project_id)


@router.put("/projects/{project_id}/questions/{qid}", response_model=RfpProjectOut)
def edit_answer(project_id: int, qid: int, body: RfpAnswerIn, user: Principal = Depends(current_user)) -> RfpProjectOut:
    """Edits a draft or writes an answer by hand, on any status; the sources stay as they are."""
    with transaction() as s:
        q = _question(s, project_id, qid)
        ids = [src["entry_id"] for src in q.sources]
        review_bys = list(s.scalars(select(m.RfpLibraryEntry.review_by).where(m.RfpLibraryEntry.id.in_(ids)))) if ids else []
        q.answer, q.status, q.last_editor = body.answer, EDITED, user.user_id
        q.flags = flags_for(body.answer, review_bys, store.today())
        return store.project_out(s, _project(s, project_id))


@router.put("/projects/{project_id}/questions/{qid}/assignee", response_model=RfpProjectOut)
def assign(project_id: int, qid: int, body: RfpAssigneeIn) -> RfpProjectOut:
    with transaction() as s:
        _question(s, project_id, qid).assignee = body.user_id or None
        return store.project_out(s, _project(s, project_id))


@router.post("/projects/{project_id}/questions/{qid}/leave-blank", response_model=RfpProjectOut)
def leave_blank(project_id: int, qid: int) -> RfpProjectOut:
    with transaction() as s:
        _question(s, project_id, qid).status = LEFT_BLANK
        return store.project_out(s, _project(s, project_id))


@router.post("/projects/{project_id}/questions/{qid}/approve", response_model=RfpProjectOut)
def approve(project_id: int, qid: int, body: RfpApproveIn, user: Principal = Depends(_approver)) -> RfpProjectOut:
    """Four-eyes: the approver confirms every flag and may not be the answer's last editor. The answer becomes a new
    library entry."""
    with transaction() as s:
        q = _question(s, project_id, qid, lock=True)  # two approvers at once: the second waits, then sees `approved`
        if q.status not in (DRAFTED, EDITED):
            raise HTTPException(409, f"Only a drafted or edited answer can be approved; this one is {q.status}.")
        if not q.answer.strip():
            raise HTTPException(409, "An empty answer cannot be approved.")
        missing = [f for f in q.flags if f not in body.confirmed_flags]
        if missing:
            raise HTTPException(409, f"Confirm every flag before approving: {', '.join(missing)}.")
        if q.last_editor == user.user_id:
            raise HTTPException(403, "You edited this answer last; another approver must approve it.")
        q.status = APPROVED
        day = store.today()
        s.add(m.RfpLibraryEntry(
            question=q.question, answer=q.answer, tags=[], source_project_id=project_id if q.sources else None,
            written_by=None if q.sources else q.last_editor, approved_on=day, review_by=plus_12_months(day),
            owner=user.user_id, has_figures=has_figures(q.answer), status="active",
        ))
        return store.project_out(s, _project(s, project_id))


@router.get("/projects/{project_id}/export")
def export(project_id: int, blobs=Depends(blob_store_dep)) -> Response:
    """The investor's original file with every approved answer written in. `X-RFP-Unapproved`: questions not approved."""
    with transaction() as s:
        p = _project(s, project_id)
        questions = store.questions_of(s, project_id)
        filename, key = p.filename, p.content_key
        answers = [(q.answer_location, q.answer) for q in questions if q.status == APPROVED]
        unapproved = len(questions) - len(answers)
    suffix = _suffix(filename)
    try:
        data = fill(blobs.get(key), suffix, answers)
    except FillRefused as exc:
        raise HTTPException(409, str(exc)) from None
    fallback = filename.encode("ascii", "replace").decode().replace("?", "_").replace('"', "")  # headers are latin-1
    return Response(data, media_type=_MEDIA[suffix], headers={
        "Content-Disposition": f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}",
        "X-RFP-Unapproved": str(unapproved),
    })
