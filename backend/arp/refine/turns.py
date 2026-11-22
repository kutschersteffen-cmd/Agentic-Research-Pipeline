"""The Refine turn log: one `running` turn per document, enforced by a partial unique index."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, type_coerce, update
from sqlalchemy.dialects.postgresql import JSONB
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
                  before: dict | None = None, after: dict | None = None, ops: list | None = None) -> bool:
    """Writes onto a `running` turn only (`result` keys are merged in) and bumps `updated_at`; False when it is not running."""
    fields = {"done": done, "total": total, "before": before, "after": after, "ops": ops}
    fields = {k: v for k, v in fields.items() if v is not None}
    if result is not None:
        fields["result"] = m.RefineTurn.result.op("||")(type_coerce(result, JSONB))
    with transaction() as s:
        return s.execute(_running(turn_id).values(**fields, updated_at=func.now())).rowcount == 1


def finish_turn(turn_id: int, status: str, *, error: str | None = None) -> bool:
    """False when the turn is no longer `running` (e.g. reaped), which it then stays."""
    with transaction() as s:
        return s.execute(_running(turn_id).values(status=status, error=error)).rowcount == 1


def drop_turn(turn_id: int) -> None:
    """Deletes undo's lock row, so the turn list never shows it."""
    with transaction() as s:
        s.execute(delete(m.RefineTurn).where(m.RefineTurn.id == turn_id))


def _running(turn_id: int):
    return update(m.RefineTurn).where(m.RefineTurn.id == turn_id, m.RefineTurn.status == "running")


def reap_stale_turns(now: datetime | None = None) -> int:
    """Fail `running` turns with no progress for the timeout; with `now=None` (API start) every `running` turn."""
    q = update(m.RefineTurn).where(m.RefineTurn.status == "running")
    if now is not None:
        q = q.where(func.coalesce(m.RefineTurn.updated_at, m.RefineTurn.created_at) < now - timedelta(minutes=REFINE_TURN_TIMEOUT_MIN))
    with transaction() as s:
        return s.execute(q.values(status="failed", error="interrupted")).rowcount


def _out(t: m.RefineTurn) -> dict:
    r = t.result or {}
    return {"status": t.status, "reply": r.get("reply"), "done": t.done, "total": t.total,
            "changed": r.get("changed", []), "not_changed": r.get("not_changed", []),
            "check_figures": r.get("check_figures", []), "error": t.error}


def turn_out(turn_id: int) -> dict:
    with transaction() as s:
        t = s.execute(select(m.RefineTurn).where(m.RefineTurn.id == turn_id)).scalar_one()
        return {"id": t.id, **_out(t), "reply": (t.result or {}).get("reply", "")}


def list_turns(kind: str, doc_id: str) -> list[dict]:
    """The document's turns, oldest first, every status; `reply` is None until the model call returns."""
    with transaction() as s:
        turns = s.scalars(select(m.RefineTurn).where(m.RefineTurn.kind == kind, m.RefineTurn.doc_id == doc_id)
                          .order_by(m.RefineTurn.created_at, m.RefineTurn.id))
        return [{"turn_id": t.id, "user_id": t.user_id, "message": t.message, "created_at": t.created_at, **_out(t)}
                for t in turns]
