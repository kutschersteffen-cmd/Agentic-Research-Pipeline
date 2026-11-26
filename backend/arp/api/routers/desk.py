"""Research Desk: chats with a scope (companies, saved universes, runs), each question answered in the background
from the scope's stored reports (spec research-desk-wave1, slice 1). A chat is visible to its owner only."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from arp.api.auth import Principal, require_role
from arp.api.deps import get_llm_client, get_run_store
from arp.api.run_scheduling import keep_task
from arp.config import get_settings
from arp.db import models as m
from arp.db.session import transaction
from arp.research_desk.turn import (
    STAGES,
    company_names,
    reap_stale_desk_turns,
    report_files,
    run_turn,
    scope_companies,
)
from arp.storage.safe_path import UnsafeIdentifierError, safe_id

router = APIRouter(prefix="/api/desk", tags=["desk"])
_analyst = require_role("analyst")
MAX_SCOPE = 50
MAX_QUESTION_CHARS = 2000
MAX_RUNNING_PER_USER = 3
BUSY = "A question is already running in this chat."


class DeskChatIn(BaseModel):
    title: str | None = None


class DeskChatCreated(BaseModel):
    id: int
    title: str
    created_at: datetime


class DeskChatListItem(BaseModel):
    id: int
    title: str
    updated_at: datetime
    turns: int


class DeskScopeItemIn(BaseModel):
    kind: Literal["company", "universe", "run"]
    ref: str


class DeskScopeIn(BaseModel):
    items: list[DeskScopeItemIn]


class DeskScopeItem(BaseModel):
    kind: str
    ref: str
    label: str


class DeskScopeOut(BaseModel):
    scope: list[DeskScopeItem]


class DeskTurnSummary(BaseModel):
    id: int
    question: str
    mode: str
    status: str
    created_at: datetime


class DeskChatOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    scope: list[DeskScopeItem]
    turns: list[DeskTurnSummary]


class DeskCompany(BaseModel):
    company_id: str
    name: str
    reports: int


class DeskCompanies(BaseModel):
    total: int
    items: list[DeskCompany]


class DeskTurnIn(BaseModel):
    question: str
    mode: Literal["quick", "thorough"] = "quick"


class DeskTurnStarted(BaseModel):
    turn_id: int


class DeskStage(BaseModel):
    name: str
    status: str
    ms: int | None
    detail: dict | None


class DeskTurnOut(BaseModel):
    id: int
    chat_id: int
    question: str
    mode: str
    status: str
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    stages: list[DeskStage]
    sources: list[dict]
    answer: dict | None


def _chat(s, chat_id: int, user: Principal) -> m.DeskChat:
    chat = s.get(m.DeskChat, chat_id)
    if chat is None or chat.owner_id != user.user_id:
        raise HTTPException(404, "Chat not found")
    return chat


def _scope(s, chat_id: int) -> list[dict]:
    return [{"kind": x.kind, "ref": x.ref, "label": x.label}
            for x in s.scalars(select(m.DeskScope).where(m.DeskScope.chat_id == chat_id).order_by(m.DeskScope.id))]


@router.post("/chats", status_code=201, response_model=DeskChatCreated)
def create_chat(body: DeskChatIn, user: Principal = Depends(_analyst)) -> dict:
    with transaction() as s:
        chat = m.DeskChat(owner_id=user.user_id, title=body.title or "New chat")
        s.add(chat)
        s.flush()
        s.refresh(chat)
        return {"id": chat.id, "title": chat.title, "created_at": chat.created_at}


@router.get("/chats", response_model=list[DeskChatListItem])
def list_chats(user: Principal = Depends(_analyst)) -> list[dict]:
    turns = select(func.count(m.DeskTurn.id)).where(m.DeskTurn.chat_id == m.DeskChat.id).scalar_subquery()
    with transaction() as s:
        rows = s.execute(select(m.DeskChat, turns).where(m.DeskChat.owner_id == user.user_id)
                         .order_by(m.DeskChat.updated_at.desc(), m.DeskChat.id.desc()).limit(20)).all()
        return [{"id": c.id, "title": c.title, "updated_at": c.updated_at, "turns": n} for c, n in rows]


@router.get("/chats/{chat_id}", response_model=DeskChatOut)
def get_chat(chat_id: int, user: Principal = Depends(_analyst)) -> dict:
    with transaction() as s:
        chat = _chat(s, chat_id, user)
        turns = s.scalars(select(m.DeskTurn).where(m.DeskTurn.chat_id == chat_id).order_by(m.DeskTurn.id))
        return {"id": chat.id, "title": chat.title, "created_at": chat.created_at, "scope": _scope(s, chat_id),
                "turns": [{"id": t.id, "question": t.question, "mode": t.mode, "status": t.status,
                           "created_at": t.created_at} for t in turns]}


@router.put("/chats/{chat_id}/scope", response_model=DeskScopeOut)
def put_scope(chat_id: int, body: DeskScopeIn, user: Principal = Depends(_analyst)) -> dict:
    with transaction() as s:
        _chat(s, chat_id, user)
    items = list(dict.fromkeys((i.kind, i.ref) for i in body.items))
    if len(items) > MAX_SCOPE:
        raise HTTPException(422, "Scope is limited to 50 companies.")
    names = company_names()
    rows, companies = [], set()
    for kind, ref in items:
        if kind == "company":
            if not _company_folder(ref) and ref.upper() not in names:
                raise HTTPException(422, f"Unknown company: {ref}")
            label = names.get(ref.upper(), ref)
        elif kind == "universe":
            label = Path(ref).name
        else:
            if get_run_store().load_manifest(ref) is None:
                raise HTTPException(422, f"Unknown run: {ref}")
            label = ref
        companies.update(scope_companies(kind, ref))
        rows.append(m.DeskScope(chat_id=chat_id, kind=kind, ref=ref, label=label))
    if len(companies) > MAX_SCOPE:
        raise HTTPException(422, "Scope is limited to 50 companies.")
    with transaction() as s:
        s.execute(delete(m.DeskScope).where(m.DeskScope.chat_id == chat_id))
        s.add_all(rows)
        s.execute(update(m.DeskChat).where(m.DeskChat.id == chat_id).values(updated_at=func.now()))
        s.flush()
        return {"scope": _scope(s, chat_id)}


def _company_folder(key: str) -> bool:
    try:
        return (get_settings().documents_dir / safe_id(key, label="company_id")).is_dir()
    except UnsafeIdentifierError:
        return False


@router.get("/companies", response_model=DeskCompanies)
def list_companies(q: str = "", limit: int = Query(20, ge=1, le=100), user: Principal = Depends(_analyst)) -> dict:
    folder = get_settings().documents_dir
    names = company_names()
    items = []
    for key in sorted(p.name for p in folder.iterdir()) if folder.is_dir() else ():
        reports = len(report_files(key))
        name = names.get(key.upper(), key)
        if reports and (q.lower() in name.lower() or q.lower() in key.lower()):
            items.append({"company_id": key, "name": name, "reports": reports})
    items.sort(key=lambda c: c["name"].lower())
    return {"total": len(items), "items": items[:limit]}


@router.post("/chats/{chat_id}/turns", status_code=202, response_model=DeskTurnStarted)
async def post_turn(chat_id: int, body: DeskTurnIn, user: Principal = Depends(_analyst)) -> DeskTurnStarted:
    question = body.question.strip()
    with transaction() as s:
        _chat(s, chat_id, user)
    if not 1 <= len(question) <= MAX_QUESTION_CHARS:
        raise HTTPException(422, "A question is 1 to 2000 characters.")
    reap_stale_desk_turns(now=datetime.now(UTC))  # a turn whose task died must not lock its chat until restart
    with transaction() as s:
        if not _scope(s, chat_id):
            raise HTTPException(409, "Add a company, universe, run or upload to this chat first.")
        running = s.execute(select(m.DeskTurn.chat_id).join(m.DeskChat, m.DeskChat.id == m.DeskTurn.chat_id)
                            .where(m.DeskTurn.status == "running", m.DeskChat.owner_id == user.user_id)).scalars().all()
    if chat_id in running:
        raise HTTPException(409, BUSY)
    if len(running) >= MAX_RUNNING_PER_USER:
        raise HTTPException(429, "You have 3 questions running. Wait for one to finish.")
    llm = get_llm_client()  # before the turn exists: a missing key leaves no turn behind
    try:
        with transaction() as s:  # own transaction: the partial unique index is the lock across API workers
            chat = s.get(m.DeskChat, chat_id)
            first = s.scalar(select(func.count(m.DeskTurn.id)).where(m.DeskTurn.chat_id == chat_id)) == 0
            turn = m.DeskTurn(chat_id=chat_id, user_id=user.user_id, question=question, mode=body.mode,
                              stages=[{"name": n, "status": "pending", "ms": None, "detail": None} for n in STAGES])
            s.add(turn)
            if first and chat.title == "New chat":
                chat.title = question[:60]
            chat.updated_at = func.now()
            s.flush()
            turn_id = turn.id
    except IntegrityError as e:
        if "uq_desk_turns_running" in str(e.orig):
            raise HTTPException(409, BUSY) from None
        raise
    keep_task(run_turn(turn_id, llm))
    return DeskTurnStarted(turn_id=turn_id)


@router.get("/turns/{turn_id}", response_model=DeskTurnOut)
def get_turn(turn_id: int, user: Principal = Depends(_analyst)) -> dict:
    with transaction() as s:
        t = s.get(m.DeskTurn, turn_id)
        if t is None or s.get(m.DeskChat, t.chat_id).owner_id != user.user_id:
            raise HTTPException(404, "Turn not found")
        return {"id": t.id, "chat_id": t.chat_id, "question": t.question, "mode": t.mode, "status": t.status,
                "error": t.error, "created_at": t.created_at, "finished_at": t.finished_at, "stages": t.stages or [],
                "sources": t.sources or [], "answer": t.answer}


def _turn_stages(turn_id: int, user: Principal) -> tuple[str, list[dict]]:
    with transaction() as s:
        t = s.get(m.DeskTurn, turn_id)
        if t is None or s.get(m.DeskChat, t.chat_id).owner_id != user.user_id:
            raise HTTPException(404, "Turn not found")
        return t.status, t.stages or []


@router.get("/turns/{turn_id}/events", response_class=StreamingResponse)
def turn_events(turn_id: int, user: Principal = Depends(_analyst)) -> StreamingResponse:
    """Server-sent events: every stage record, then each one that changes (polled every 0.5 s, no connection held
    between polls), then `end` once the turn is no longer running."""
    _turn_stages(turn_id, user)

    async def stream():
        sent: list[dict] = []
        while True:
            status, stages = _turn_stages(turn_id, user)
            for i, stage in enumerate(stages):
                if i >= len(sent) or sent[i] != stage:
                    yield f"event: stage\ndata: {json.dumps(stage)}\n\n"
            sent = stages
            if status != "running":
                yield f"event: end\ndata: {json.dumps({'status': status})}\n\n"
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream")
