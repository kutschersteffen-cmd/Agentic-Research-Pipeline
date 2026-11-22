"""Refine chat: start a turn (it runs in the background), read it or the document's turns, undo the last one.
RFP documents only until the deck operations land; `deck` answers 404 like any unknown kind."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arp.api.auth import ROLE_RANK, Principal, current_user
from arp.api.deps import get_run_store
from arp.api.run_scheduling import schedule_llm_run
from arp.db import models as m
from arp.db.session import transaction
from arp.orchestration.job_manager import JobManager
from arp.refine.agent import run_turn
from arp.refine.turns import TurnBusy, finish_turn, list_turns, reap_stale_turns, start_turn, turn_out
from arp.refine.undo import UndoRefused, undo_last
from arp.rfp import store as rfp_store

router = APIRouter(prefix="/api/refine", tags=["refine"])
KINDS = ("rfp",)  # "deck" joins with the deck operations
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


def _doc(doc_id: str) -> str:
    """The project id in one spelling (`07` is `7`), so the turn lock and the thread are per project; else 404."""
    if not (doc_id.isascii() and doc_id.isdigit()):
        raise HTTPException(404, "RFP project not found")
    return str(int(doc_id))


def _check_doc(doc_id: str) -> None:
    with transaction() as s:
        if s.get(m.RfpProject, int(doc_id)) is None:
            raise HTTPException(404, "RFP project not found")


@router.post("/{kind}/{doc_id}/turns", status_code=202, response_model=RefineTurnStarted)
async def post_turn(body: RefineTurnIn, kind: str = Depends(_kind), user: Principal = Depends(_editor),
                    doc_id: str = Depends(_doc), run_store=Depends(get_run_store)) -> RefineTurnStarted:
    _check_doc(doc_id)
    reap_stale_turns(now=datetime.now(UTC))  # a turn whose background task died must not lock its document until restart
    try:
        turn_id = start_turn(kind, doc_id, user.user_id, body.message)  # before scheduling: a busy document is a 409 now
    except TurnBusy:
        raise HTTPException(409, BUSY) from None
    history = [h.model_dump() for h in body.history if h.reply]

    def create() -> str:
        return JobManager(run_store).create_run("refine", {"turn_id": turn_id, "kind": kind, "doc_id": doc_id}, 0).run_id

    async def run(run_id, llm, verifier) -> None:
        await run_turn(turn_id, doc_id, body.message, history, llm, today=rfp_store.today(), verifier=verifier)
        JobManager(run_store).finish_run(run_id)

    try:
        schedule_llm_run(create_fn=create, run=run)
    except Exception as exc:
        finish_turn(turn_id, "failed", error=str(exc))
        raise
    return RefineTurnStarted(turn_id=turn_id)


@router.get("/turns/{turn_id}", response_model=RefineTurnOut)
def get_turn(turn_id: int) -> dict:
    with transaction() as s:
        if s.get(m.RefineTurn, turn_id) is None:
            raise HTTPException(404, "Turn not found")
    return turn_out(turn_id)


@router.get("/{kind}/{doc_id}/turns", response_model=list[RefineTurn])
def get_turns(kind: str = Depends(_kind), doc_id: str = Depends(_doc)) -> list[dict]:
    """Any signed-in role; a document with no turns answers []."""
    return list_turns(kind, doc_id)


@router.post("/{kind}/{doc_id}/undo", response_model=RefineTurnOut)
def undo(kind: str = Depends(_kind), user: Principal = Depends(_editor), doc_id: str = Depends(_doc)) -> dict:
    reap_stale_turns(now=datetime.now(UTC))
    try:
        return turn_out(undo_last(kind, doc_id, user.user_id))
    except TurnBusy:
        raise HTTPException(409, BUSY) from None
    except UndoRefused as exc:
        raise HTTPException(409, str(exc)) from None
