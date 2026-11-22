"""Agent board API: the blocks of a thread's board (spec docs/superpowers/specs/2026-11-22-agent-board.md, "API").

Bodies are read by hand, so a body that is not a JSON object answers the spec's `invalid block` rather than
FastAPI's validation list.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from arp.agent_board.checks import BlockInvalid, check_block, check_title, render, storable
from arp.agent_board.draw import DrawRefused, draw, unverified
from arp.agent_board.store import MAX_BLOCKS, BlockNotFound, BoardFull, BoardStore, NothingToUndo
from arp.config import get_settings
from arp.db.session import require_dsn
from arp.llm.base import LLMClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent/boards", tags=["agent-board"])
THREAD_KINDS = ("plan",)  # `exploration` joins in slice 4
_ABSENT = object()


def board_store() -> BoardStore:
    return BoardStore(require_dsn(get_settings()))


def draw_llm() -> Callable[[], LLMClient]:
    """Builds the model client only after the draw's own checks, so a refused request never needs a model key."""
    from arp.api.deps import get_llm_client

    return get_llm_client


def _thread(thread_kind: str, thread_id: str, store: BoardStore) -> None:
    if thread_kind not in THREAD_KINDS:
        raise HTTPException(404, "unknown thread kind")
    if not store.plan_exists(thread_id):
        raise HTTPException(404, "thread not found")


def _reject_constant(name: str) -> None:
    raise ValueError(f"{name} is not JSON")  # NaN and Infinity: Postgres JSON refuses them


async def _body(request: Request) -> dict:
    try:
        body = json.loads(await request.body(), parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        body = None
    if not isinstance(body, dict) or not storable(body):
        raise HTTPException(422, "invalid block")
    return body


def _int(v: Any) -> int:
    if not isinstance(v, int) or isinstance(v, bool):
        raise HTTPException(422, "invalid block")
    return v


def _out(row: dict, rendered: Any = _ABSENT) -> dict:
    keys = ("id", "kind", "title", "source", "position", "version", "origin", "unverified", "created_at", "updated_at")
    out = {k: row[k] for k in keys}
    if rendered is _ABSENT:
        try:
            rendered = render(row["kind"], row["source"])
        except Exception:  # noqa: BLE001 - a block that no longer draws must not hide the rest of the board
            logger.warning("agent board: block %s does not render", row["id"], exc_info=True)
            rendered = None
    out["rendered"] = rendered
    return out


def _checked(kind: Any, title: Any, source: Any) -> Any:
    try:
        return check_block(kind, title, source)
    except BlockInvalid as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/{thread_kind}/{thread_id}")
def get_board(thread_kind: str, thread_id: str, store: BoardStore = Depends(board_store)) -> dict:
    _thread(thread_kind, thread_id, store)
    blocks = [_out(r) for r in store.blocks(thread_kind, thread_id)]
    return {"thread_kind": thread_kind, "thread_id": thread_id, "blocks": blocks}


def _create(thread_kind: str, thread_id: str, body: dict, store: BoardStore) -> dict:
    _thread(thread_kind, thread_id, store)
    kind, title, source = body.get("kind"), body.get("title"), body.get("source")
    rendered = _checked(kind, title, source)
    origin = body.get("origin", "person")
    unverified = body.get("unverified", [])
    if origin not in ("person", "agent") or not isinstance(unverified, list) or not all(
            isinstance(n, int | float) and not isinstance(n, bool) for n in unverified):
        raise HTTPException(422, "invalid block")
    if kind in ("note", "flow"):
        unverified = []  # spec "Data": always empty for these kinds
    position = _int(body["position"]) if body.get("position") is not None else None
    try:
        row = store.create(thread_kind, thread_id, kind, title.strip(), source, origin, unverified, position)
    except BoardFull:
        raise HTTPException(409, "board is full (50 blocks)") from None
    return _out(row, rendered)


@router.post("/{thread_kind}/{thread_id}/blocks", status_code=201)
async def create_block(thread_kind: str, thread_id: str, request: Request,
                       store: BoardStore = Depends(board_store)) -> dict:
    body = await _body(request)
    return await asyncio.to_thread(_create, thread_kind, thread_id, body, store)


def _get_block(store: BoardStore, thread_kind: str, thread_id: str, block_id: str) -> dict:
    row = next((r for r in store.blocks(thread_kind, thread_id) if r["id"] == block_id), None)
    if row is None:
        raise HTTPException(404, "block not found")
    return row


def _patch(thread_kind: str, thread_id: str, block_id: str, body: dict, store: BoardStore) -> dict:
    _thread(thread_kind, thread_id, store)
    row = _get_block(store, thread_kind, thread_id, block_id)
    title = body.get("title")
    if title is not None:
        try:
            title = check_title(title)
        except BlockInvalid as exc:
            raise HTTPException(422, str(exc)) from None
    source, rendered, missing = body.get("source"), _ABSENT, None
    if source is not None:
        rendered = _checked(row["kind"], title or row["title"], source)
        if row["kind"] in ("chart", "table"):  # D4: a person's edit keeps the line for numbers still missing
            missing = unverified(row["kind"], source, store.plan_data(thread_id))
    position = _int(body["position"]) if body.get("position") is not None else None
    try:
        row = store.patch(thread_kind, thread_id, block_id, title, source, position, missing)
    except BlockNotFound:
        raise HTTPException(404, "block not found") from None
    return _out(row, rendered)


@router.patch("/{thread_kind}/{thread_id}/blocks/{block_id}")
async def patch_block(thread_kind: str, thread_id: str, block_id: str, request: Request,
                      store: BoardStore = Depends(board_store)) -> dict:
    body = await _body(request)
    return await asyncio.to_thread(_patch, thread_kind, thread_id, block_id, body, store)


@router.post("/{thread_kind}/{thread_id}/blocks/{block_id}/undo")
def undo_block(thread_kind: str, thread_id: str, block_id: str, store: BoardStore = Depends(board_store)) -> dict:
    _thread(thread_kind, thread_id, store)
    try:
        row = store.undo(thread_kind, thread_id, block_id)
    except BlockNotFound:
        raise HTTPException(404, "block not found") from None
    except NothingToUndo:
        raise HTTPException(409, "nothing to undo") from None
    return _out(row)


@router.delete("/{thread_kind}/{thread_id}/blocks/{block_id}", status_code=204)
def delete_block(thread_kind: str, thread_id: str, block_id: str,
                 store: BoardStore = Depends(board_store)) -> Response:
    _thread(thread_kind, thread_id, store)
    try:
        store.delete(thread_kind, thread_id, block_id)
    except BlockNotFound:
        raise HTTPException(404, "block not found") from None
    return Response(status_code=204)


def _draw_checks(thread_kind: str, thread_id: str, body: dict, store: BoardStore) -> tuple[str, dict | None, dict]:
    """Every check that runs before a model call; returns the prompt, the current block and the thread data."""
    _thread(thread_kind, thread_id, store)
    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 2000:
        raise HTTPException(422, "prompt must be 1 to 2000 characters")
    current = None
    if body.get("block_id") is not None:
        current = _get_block(store, thread_kind, thread_id, body["block_id"])
    elif len(store.blocks(thread_kind, thread_id)) >= MAX_BLOCKS:
        raise HTTPException(409, "board is full (50 blocks)")
    return prompt, current, store.plan_data(thread_id)


@router.post("/{thread_kind}/{thread_id}/draw")
async def draw_block(thread_kind: str, thread_id: str, request: Request, store: BoardStore = Depends(board_store),
                     llm: Callable[[], LLMClient] = Depends(draw_llm)) -> dict:
    body = await _body(request)
    prompt, current, data = await asyncio.to_thread(_draw_checks, thread_kind, thread_id, body, store)
    client = llm()  # a missing model key is a configuration error, not a failed model call
    try:
        draft, rendered, missing = await draw(client, prompt, data, current)
    except DrawRefused as exc:
        raise HTTPException(422, f"the agent could not draw this: {exc}") from None
    except Exception:  # noqa: BLE001 - spec: any model failure is a 502, nothing stored
        logger.warning("agent board: draw model call failed", exc_info=True)
        raise HTTPException(502, "the agent could not draw this: model call failed") from None
    title = draft.title.strip()
    try:
        if current is None:
            row = await asyncio.to_thread(store.create, thread_kind, thread_id, draft.kind, title, draft.source,
                                          "agent", missing)
        else:
            row = await asyncio.to_thread(store.redraw, thread_kind, thread_id, current["id"], draft.kind, title,
                                          draft.source, missing)
    except BoardFull:
        raise HTTPException(409, "board is full (50 blocks)") from None
    except BlockNotFound:
        raise HTTPException(404, "block not found") from None
    return _out(row, rendered)
