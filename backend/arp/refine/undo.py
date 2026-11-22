"""Refine chat undo: restore the newest done or failed turn's `before`, unless something changed its items since."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, text

from arp.db import models as m
from arp.db.session import transaction
from arp.refine.rfp_ops import question_state
from arp.refine.turns import drop_turn, start_turn

NOTHING_TO_UNDO = "Nothing to undo."
_CONFLICT = "{} changed after this turn; undo would overwrite it."


class UndoRefused(Exception):
    """Nothing to undo, or undo would overwrite a later change; the message is the 409 detail."""


def undo_last(kind: str, doc_id: str, user_id: str) -> int:
    """Undoes the newest `done` or `failed` turn that changed something, whoever made it; returns its id. Holds the
    document's turn lock (a `running` row, deleted afterwards so it never shows as a turn) while it runs, so it cannot
    race a turn. RFP only; deck undo comes with the deck operations."""
    lock = start_turn(kind, doc_id, user_id, "undo")
    try:
        with transaction() as s:
            t = s.scalars(select(m.RefineTurn).where(
                m.RefineTurn.kind == kind, m.RefineTurn.doc_id == doc_id, m.RefineTurn.status.in_(("done", "failed")),
                m.RefineTurn.before != text("'{}'::jsonb"),
            ).order_by(m.RefineTurn.id.desc()).limit(1).with_for_update()).first()
            if t is None:
                raise UndoRefused(NOTHING_TO_UNDO)
            qs = {str(q.id): q for q in s.scalars(select(m.RfpQuestion).where(
                m.RfpQuestion.id.in_([int(k) for k in t.after])).with_for_update())}
            for k in sorted(t.after, key=int):
                if k not in qs or question_state(qs[k]) != t.after[k]:
                    raise UndoRefused(_CONFLICT.format(f"Q{k}"))
            for k, v in t.before.items():
                for field, value in v.items():
                    setattr(qs[k], field, value)
            t.status, t.undone_at = "undone", datetime.now(UTC)
            return t.id
    finally:
        drop_turn(lock)
