"""Refine chat undo: restore the newest done or failed turn's `before`, unless something changed its items since."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, text

from arp.db import models as m
from arp.db.session import transaction
from arp.refine.agent import mark_deck_edited
from arp.refine.rfp_ops import question_state
from arp.refine.turns import drop_turn, start_turn
from arp.schemas.reporting import Deck
from arp.storage.reporting_store import ReportingStore

NOTHING_TO_UNDO = "Nothing to undo."
_CONFLICT = "{} changed after this turn; undo would overwrite it."


class UndoRefused(Exception):
    """Nothing to undo, or undo would overwrite a later change; the message is the 409 detail."""


def _first_changed_slide(current: list, after: list) -> int:
    """The first position whose slide differs, or the first position past the shorter list."""
    return next((i for i, (c, a) in enumerate(zip(current, after, strict=False), 1) if c != a),
                min(len(current), len(after)) + 1)


def undo_last(kind: str, doc_id: str, user_id: str, store: ReportingStore) -> int:
    """Undoes the newest `done` or `failed` turn that changed something, whoever made it; returns its id. Holds the
    document's turn lock (a `running` row, deleted afterwards so it never shows as a turn) while it runs, so it cannot
    race a turn."""
    lock = start_turn(kind, doc_id, user_id, "undo")
    try:
        with transaction() as s:
            t = s.scalars(select(m.RefineTurn).where(
                m.RefineTurn.kind == kind, m.RefineTurn.doc_id == doc_id, m.RefineTurn.status.in_(("done", "failed")),
                m.RefineTurn.before != text("'{}'::jsonb"),
            ).order_by(m.RefineTurn.id.desc()).limit(1).with_for_update()).first()
            if t is None:
                raise UndoRefused(NOTHING_TO_UNDO)
            if kind == "deck":
                _undo_deck(t, doc_id, store)
            else:
                qs = {str(q.id): q for q in s.scalars(select(m.RfpQuestion).where(
                    m.RfpQuestion.id.in_([int(k) for k in t.after])).with_for_update())}
                for k in sorted(t.after, key=int):
                    if k not in qs or question_state(qs[k]) != t.after[k]:
                        raise UndoRefused(_CONFLICT.format(f"Q{k}"))
                restore = (t.result or {}).get("restore", {})  # absent on turns logged before it was kept
                for k, v in t.before.items():
                    for field, value in {**v, **restore.get(k, {})}.items():
                        setattr(qs[k], field, value)
            t.status, t.undone_at = "undone", datetime.now(UTC)
            return t.id
    finally:
        drop_turn(lock)


def _undo_deck(t: m.RefineTurn, doc_id: str, store: ReportingStore) -> None:
    deck = store.load_deck(doc_id)
    current = deck.model_dump(mode="json") if deck else {"slides": []}
    if current != t.after:
        raise UndoRefused(_CONFLICT.format(f"Slide {_first_changed_slide(current['slides'], t.after.get('slides', []))}"))
    store.save_deck(doc_id, Deck.model_validate(t.before))
    mark_deck_edited(store, doc_id)
