"""Refine chat: start a turn (it runs in the background), read it or the document's turns, undo the last one; list the
documents that have turns (the threads) and the documents that can be refined."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from arp.api.auth import ROLE_RANK, Principal, current_user
from arp.api.deps import get_reporting_store, get_run_store
from arp.api.run_scheduling import schedule_llm_run
from arp.db import models as m
from arp.db.session import transaction
from arp.orchestration.job_manager import JobManager
from arp.refine.agent import run_turn
from arp.refine.deck_ops import NO_DECK
from arp.refine.turns import TurnBusy, finish_turn, list_turns, reap_stale_turns, start_turn, turn_out
from arp.refine.undo import UndoRefused, undo_last
from arp.rfp import store as rfp_store
from arp.storage.reporting_store import ReportingStore
from arp.storage.safe_path import UnsafeIdentifierError, safe_id

router = APIRouter(prefix="/api/refine", tags=["refine"])
KINDS = ("rfp", "deck")
TITLE_CHARS = 60
BUSY = "A change is already running on this document."


class RefineHistoryItem(BaseModel):
    message: str
    reply: str | None = None


class RefineTurnIn(BaseModel):
    message: str
    history: list[RefineHistoryItem] = []


class RefineTurnStarted(BaseModel):
    turn_id: int


class RefineNotChanged(BaseModel):
    id: int | None
    reason: str


class RefineTurnOut(BaseModel):
    id: int
    status: str
    reply: str
    done: int
    total: int
    changed: list[int]
    not_changed: list[RefineNotChanged]
    check_figures: list[int]
    error: str | None


class RefineTurn(BaseModel):
    turn_id: int
    user_id: str
    message: str
    reply: str | None
    status: str
    done: int
    total: int
    changed: list[int]
    not_changed: list[RefineNotChanged]
    check_figures: list[int]
    error: str | None
    created_at: datetime


def _kind(kind: str) -> str:
    if kind not in KINDS:
        raise HTTPException(404, "Unknown document kind.")
    return kind


async def _editor(user: Principal = Depends(current_user)) -> Principal:
    if ROLE_RANK[user.role] < ROLE_RANK["analyst"]:
        raise HTTPException(403, "Viewers cannot change documents.")
    return user


class RefineThread(BaseModel):
    kind: str
    doc_id: str
    title: str
    status: str
    last_turn_at: datetime
    turns: int


class RefineDocument(BaseModel):
    kind: str
    doc_id: str
    title: str


def _check_doc(kind: str, doc_id: str, store: ReportingStore) -> None:
    if kind == "deck":
        try:
            folder = store.reports_dir / safe_id(doc_id, label="report_id")
        except UnsafeIdentifierError:
            raise HTTPException(404, "Report not found") from None
        if not (folder / "manifest.json").exists():  # first: load_deck goes through report_dir(), which creates the folder
            raise HTTPException(404, "Report not found")
        if store.load_deck(doc_id) is None:
            raise HTTPException(409, NO_DECK)
        return
    with transaction() as s:
        if not doc_id.isdigit() or s.get(m.RfpProject, int(doc_id)) is None:
            raise HTTPException(404, "RFP project not found")


@router.post("/{kind}/{doc_id}/turns", status_code=202, response_model=RefineTurnStarted)
async def post_turn(doc_id: str, body: RefineTurnIn, kind: str = Depends(_kind), user: Principal = Depends(_editor),
                    store: ReportingStore = Depends(get_reporting_store), run_store=Depends(get_run_store)) -> RefineTurnStarted:
    _check_doc(kind, doc_id, store)
    reap_stale_turns(now=datetime.now(UTC))  # a turn whose background task died must not lock its document until restart
    try:
        turn_id = start_turn(kind, doc_id, user.user_id, body.message)  # before scheduling: a busy document is a 409 now
    except TurnBusy:
        raise HTTPException(409, BUSY) from None
    history = [h.model_dump() for h in body.history if h.reply]

    def create() -> str:
        return JobManager(run_store).create_run("refine", {"turn_id": turn_id, "kind": kind, "doc_id": doc_id}, 0).run_id

    async def run(run_id, llm, verifier) -> None:
        await run_turn(turn_id, kind, doc_id, body.message, history, llm, store, today=rfp_store.today(), verifier=verifier)
        JobManager(run_store).finish_run(run_id)

    try:
        schedule_llm_run(create_fn=create, run=run)
    except Exception as exc:
        finish_turn(turn_id, "failed", error=str(exc))
        raise
    return RefineTurnStarted(turn_id=turn_id)


def _title(kind: str, name: str) -> str:
    return f"{'RFP' if kind == 'rfp' else 'Deck'}: {name}"[:TITLE_CHARS]


def _rfp_titles(s, ids: list[int] | None = None) -> dict[str, str]:
    """Project id -> title, newest project first."""
    q = select(m.RfpProject.id, m.RfpProject.investor).order_by(m.RfpProject.created_at.desc(), m.RfpProject.id.desc())
    if ids is not None:
        q = q.where(m.RfpProject.id.in_(ids))
    return {str(pid): _title("rfp", investor) for pid, investor in s.execute(q)}


def _deck_titles(store: ReportingStore) -> dict[str, str]:
    """Report id -> title for every report with a deck, newest report first."""
    return {r.report_id: _title("deck", r.title) for r in store.list_reports() if r.has_deck}


@router.get("/threads", response_model=list[RefineThread])
def get_threads(store: ReportingStore = Depends(get_reporting_store)) -> list[dict]:
    """One row per document with at least one turn, newest first by its newest turn. Any signed-in role."""
    threads: dict[tuple[str, str], dict] = {}
    with transaction() as s:
        for kind, doc_id, status, created_at in s.execute(
                select(m.RefineTurn.kind, m.RefineTurn.doc_id, m.RefineTurn.status, m.RefineTurn.created_at)
                .order_by(m.RefineTurn.created_at, m.RefineTurn.id)):
            t = threads.setdefault((kind, doc_id), {"kind": kind, "doc_id": doc_id, "turns": 0})
            t.update(status=status, last_turn_at=created_at, turns=t["turns"] + 1)  # oldest first: the last one wins
        rfp_ids = [int(d) for k, d in threads if k == "rfp" and d.isdigit()]
        titles = {"rfp": _rfp_titles(s, rfp_ids) if rfp_ids else {}}
    titles["deck"] = _deck_titles(store) if any(k == "deck" for k, _ in threads) else {}
    out = [{**t, "title": titles[t["kind"]][t["doc_id"]]} for t in threads.values()
           if t["doc_id"] in titles.get(t["kind"], {})]  # a deleted document has no thread
    return sorted(out, key=lambda t: t["last_turn_at"], reverse=True)


@router.get("/documents", response_model=list[RefineDocument])
def get_documents(store: ReportingStore = Depends(get_reporting_store)) -> list[dict]:
    """Every RFP project, then every report with a deck, each group newest first. Any signed-in role."""
    with transaction() as s:
        rfps = _rfp_titles(s)
    return [*({"kind": "rfp", "doc_id": d, "title": t} for d, t in rfps.items()),
            *({"kind": "deck", "doc_id": d, "title": t} for d, t in _deck_titles(store).items())]


@router.get("/turns/{turn_id}", response_model=RefineTurnOut)
def get_turn(turn_id: int) -> dict:
    with transaction() as s:
        if s.get(m.RefineTurn, turn_id) is None:
            raise HTTPException(404, "Turn not found")
    return turn_out(turn_id)


@router.get("/{kind}/{doc_id}/turns", response_model=list[RefineTurn])
def get_turns(doc_id: str, kind: str = Depends(_kind)) -> list[dict]:
    """Any signed-in role; a document with no turns answers []."""
    return list_turns(kind, doc_id)


@router.post("/{kind}/{doc_id}/undo", response_model=RefineTurnOut)
def undo(doc_id: str, kind: str = Depends(_kind), user: Principal = Depends(_editor),
         store: ReportingStore = Depends(get_reporting_store)) -> dict:
    if kind == "deck":
        _check_doc(kind, doc_id, store)  # a deleted report is a 404, and its folder is not re-created
    reap_stale_turns(now=datetime.now(UTC))
    try:
        return turn_out(undo_last(kind, doc_id, user.user_id, store))
    except TurnBusy:
        raise HTTPException(409, BUSY) from None
    except UndoRefused as exc:
        raise HTTPException(409, str(exc)) from None
