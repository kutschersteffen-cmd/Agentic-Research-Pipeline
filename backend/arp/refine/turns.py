"""The Refine turn log: one `running` turn per document, enforced by a partial unique index."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from arp.db import models as m
from arp.db.session import transaction

REFINE_TURN_TIMEOUT_MIN = 10
REFINE_HISTORY_TURNS = 5
REFINE_MAX_QUESTIONS = 400
REFINE_ANSWER_PREVIEW_CHARS = 300


class TurnBusy(Exception):
    """The document already has a running turn."""


def start_turn(kind: str, doc_id: str, user_id: str, message: str) -> int:
    try:
        with transaction() as s:  # own transaction: the index is the lock across API workers
            t = m.RefineTurn(kind=kind, doc_id=doc_id, user_id=user_id, message=message)
            s.add(t)
            s.flush()
            return t.id
    except IntegrityError as e:
        if "uq_refine_turns_running" in str(e.orig):
            raise TurnBusy(f"{kind} {doc_id} already has a running turn") from e
        raise


def save_progress(turn_id: int, *, done: int | None = None, total: int | None = None, result: dict | None = None,
                  before: dict | None = None, after: dict | None = None, ops: list | None = None) -> None:
    fields = {"done": done, "total": total, "result": result, "before": before, "after": after, "ops": ops}
    fields = {k: v for k, v in fields.items() if v is not None}
    if fields:
        with transaction() as s:
            s.execute(update(m.RefineTurn).where(m.RefineTurn.id == turn_id).values(**fields))


def finish_turn(turn_id: int, status: str, *, error: str | None = None) -> None:
    with transaction() as s:
        s.execute(update(m.RefineTurn).where(m.RefineTurn.id == turn_id).values(status=status, error=error))


def reap_stale_turns(now: datetime | None = None) -> int:
    """Fail `running` turns older than the timeout; with `now=None` (API start) every `running` turn."""
    q = update(m.RefineTurn).where(m.RefineTurn.status == "running")
    if now is not None:
        q = q.where(m.RefineTurn.created_at < now - timedelta(minutes=REFINE_TURN_TIMEOUT_MIN))
    with transaction() as s:
        return s.execute(q.values(status="failed", error="interrupted")).rowcount


def turn_out(turn_id: int) -> dict:
    with transaction() as s:
        t = s.execute(select(m.RefineTurn).where(m.RefineTurn.id == turn_id)).scalar_one()
        r = t.result or {}
        return {"id": t.id, "status": t.status, "reply": r.get("reply", ""), "done": t.done, "total": t.total,
                "changed": r.get("changed", []), "not_changed": r.get("not_changed", []),
                "check_figures": r.get("check_figures", []), "error": t.error}
