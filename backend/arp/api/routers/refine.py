"""Refine chat: start a turn (it runs in the background), read it, undo the last one."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arp.api.auth import ROLE_RANK, Principal, current_user
from arp.api.deps import get_reporting_store, get_run_store
from arp.api.run_scheduling import schedule_llm_run
from arp.db import models as m
from arp.db.session import transaction
from arp.orchestration.job_manager import JobManager
from arp.refine.agent import NO_DECK, run_turn
from arp.refine.turns import TurnBusy, finish_turn, start_turn, turn_out
from arp.refine.undo import UndoRefused, undo_last
from arp.rfp import store as rfp_store
from arp.storage.reporting_store import ReportingStore

router = APIRouter(prefix="/api/refine", tags=["refine"])
Kind = Literal["rfp", "deck"]
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


async def _editor(user: Principal = Depends(current_user)) -> Principal:
    if ROLE_RANK[user.role] < ROLE_RANK["analyst"]:
        raise HTTPException(403, "Viewers cannot change documents.")
    return user


def _check_doc(kind: str, doc_id: str, store: ReportingStore) -> None:
    if kind == "deck":
        if store.load_deck(doc_id) is None:
            raise HTTPException(409, NO_DECK)
        return
    with transaction() as s:
        if not doc_id.isdigit() or s.get(m.RfpProject, int(doc_id)) is None:
            raise HTTPException(404, "RFP project not found")


@router.post("/{kind}/{doc_id}/turns", status_code=202, response_model=RefineTurnStarted)
async def post_turn(kind: Kind, doc_id: str, body: RefineTurnIn, user: Principal = Depends(_editor),
                    store: ReportingStore = Depends(get_reporting_store), run_store=Depends(get_run_store)) -> RefineTurnStarted:
    _check_doc(kind, doc_id, store)
    try:
        turn_id = start_turn(kind, doc_id, user.user_id, body.message)  # before scheduling: a busy document is a 409 now
    except TurnBusy:
        raise HTTPException(409, BUSY) from None
    history = [h.model_dump() for h in body.history if h.reply]

    def create() -> str:
        return JobManager(run_store).create_run("refine", {"turn_id": turn_id, "kind": kind, "doc_id": doc_id}, 0).run_id

    async def run(run_id, llm, _verifier) -> None:
        await run_turn(turn_id, kind, doc_id, body.message, history, llm, store, today=rfp_store.today())
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


@router.post("/{kind}/{doc_id}/undo", response_model=RefineTurnOut)
def undo(kind: Kind, doc_id: str, user: Principal = Depends(_editor),
         store: ReportingStore = Depends(get_reporting_store)) -> dict:
    try:
        return turn_out(undo_last(kind, doc_id, user.user_id, store))
    except TurnBusy:
        raise HTTPException(409, BUSY) from None
    except UndoRefused as exc:
        raise HTTPException(409, str(exc)) from None
