"""Agent board API: the blocks of a thread's board (spec docs/superpowers/specs/2026-11-22-agent-board.md, "API").

Bodies are read by hand, so a body that is not a JSON object answers the spec's `invalid block` rather than
FastAPI's validation list.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from arp.agent_board.checks import BlockInvalid, check_block, check_title, render
from arp.agent_board.store import BlockNotFound, BoardFull, BoardStore, NothingToUndo
from arp.config import get_settings
from arp.db.session import require_dsn

router = APIRouter(prefix="/api/agent/boards", tags=["agent-board"])
THREAD_KINDS = ("plan",)  # `exploration` joins in slice 4
_ABSENT = object()


def board_store() -> BoardStore:
    return BoardStore(require_dsn(get_settings()))


def _thread(thread_kind: str, thread_id: str, store: BoardStore) -> None:
    if thread_kind not in THREAD_KINDS:
        raise HTTPException(404, "unknown thread kind")
    if not store.plan_exists(thread_id):
        raise HTTPException(404, "thread not found")


async def _body(request: Request) -> dict:
    try:
        body = json.loads(await request.body())
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(422, "invalid block")
    return body


def _int(v: Any) -> int:
    if not isinstance(v, int) or isinstance(v, bool):
        raise HTTPException(422, "invalid block")
    return v


def _out(row: dict, rendered: Any = _ABSENT) -> dict:
    keys = ("id", "kind", "title", "source", "position", "version", "origin", "unverified", "created_at", "updated_at")
    out = {k: row[k] for k in keys}
    out["rendered"] = render(row["kind"], row["source"]) if rendered is _ABSENT else rendered
    return out


def _checked(kind: Any, title: Any, source: Any) -> Any:
    try:
        return check_block(kind, title, source)
    except BlockInvalid as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/{thread_kind}/{thread_id}")
async def get_board(thread_kind: str, thread_id: str, store: BoardStore = Depends(board_store)) -> dict:
    _thread(thread_kind, thread_id, store)
    rows = store.blocks(thread_kind, thread_id)
    blocks = await asyncio.to_thread(lambda: [_out(r) for r in rows])
    return {"thread_kind": thread_kind, "thread_id": thread_id, "blocks": blocks}


@router.post("/{thread_kind}/{thread_id}/blocks", status_code=201)
async def create_block(thread_kind: str, thread_id: str, request: Request,
                       store: BoardStore = Depends(board_store)) -> dict:
    _thread(thread_kind, thread_id, store)
    body = await _body(request)
    kind, title, source = body.get("kind"), body.get("title"), body.get("source")
    rendered = await asyncio.to_thread(_checked, kind, title, source)
    origin = body.get("origin", "person")
    unverified = body.get("unverified", [])
    if origin not in ("person", "agent") or not isinstance(unverified, list) or not all(
            isinstance(n, int | float) and not isinstance(n, bool) for n in unverified):
        raise HTTPException(422, "invalid block")
    position = _int(body["position"]) if body.get("position") is not None else None
    try:
        row = store.create(thread_kind, thread_id, kind, title.strip(), source, origin, unverified, position)
    except BoardFull:
        raise HTTPException(409, "board is full (50 blocks)") from None
    return _out(row, rendered)


def _get_block(store: BoardStore, thread_kind: str, thread_id: str, block_id: str) -> dict:
    row = next((r for r in store.blocks(thread_kind, thread_id) if r["id"] == block_id), None)
    if row is None:
        raise HTTPException(404, "block not found")
    return row


@router.patch("/{thread_kind}/{thread_id}/blocks/{block_id}")
async def patch_block(thread_kind: str, thread_id: str, block_id: str, request: Request,
                      store: BoardStore = Depends(board_store)) -> dict:
    _thread(thread_kind, thread_id, store)
    body = await _body(request)
    row = _get_block(store, thread_kind, thread_id, block_id)
    title = body.get("title")
    if title is not None:
        try:
            title = check_title(title)
        except BlockInvalid as exc:
            raise HTTPException(422, str(exc)) from None
    source = body.get("source")
    if source is not None:
        await asyncio.to_thread(_checked, row["kind"], title or row["title"], source)
    position = _int(body["position"]) if body.get("position") is not None else None
    try:
        row = store.patch(thread_kind, thread_id, block_id, title, source, position)
    except BlockNotFound:
        raise HTTPException(404, "block not found") from None
    return await asyncio.to_thread(_out, row)


@router.post("/{thread_kind}/{thread_id}/blocks/{block_id}/undo")
async def undo_block(thread_kind: str, thread_id: str, block_id: str, store: BoardStore = Depends(board_store)) -> dict:
    _thread(thread_kind, thread_id, store)
    try:
        row = store.undo(thread_kind, thread_id, block_id)
    except BlockNotFound:
        raise HTTPException(404, "block not found") from None
    except NothingToUndo:
        raise HTTPException(409, "nothing to undo") from None
    return await asyncio.to_thread(_out, row)


@router.delete("/{thread_kind}/{thread_id}/blocks/{block_id}", status_code=204)
async def delete_block(thread_kind: str, thread_id: str, block_id: str,
                       store: BoardStore = Depends(board_store)) -> Response:
    _thread(thread_kind, thread_id, store)
    try:
        store.delete(thread_kind, thread_id, block_id)
    except BlockNotFound:
        raise HTTPException(404, "block not found") from None
    return Response(status_code=204)
