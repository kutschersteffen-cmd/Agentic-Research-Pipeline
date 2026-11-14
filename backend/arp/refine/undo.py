"""Refine chat undo: restore the newest done turn's `before`, unless something changed its items since."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, text

from arp.db import models as m
from arp.db.session import transaction
from arp.refine.turns import finish_turn, start_turn
from arp.schemas.reporting import Deck
from arp.storage.reporting_store import ReportingStore

NOTHING_TO_UNDO = "Nothing to undo."
_CONFLICT = "{} changed after this turn; undo would overwrite it."


class UndoRefused(Exception):
    """Nothing to undo, or undo would overwrite a later change; the message is the 409 detail."""


def _state(q: m.RfpQuestion) -> dict:
    return {"answer": q.answer, "status": q.status, "sources": q.sources, "flags": q.flags, "last_editor": q.last_editor}


def _first_changed_slide(current: list, after: list) -> int:
    return next((i for i, (c, a) in enumerate(zip(current, after, strict=False), 1) if c != a), min(len(current), len(after)) + 1)


def undo_last(kind: str, doc_id: str, user_id: str, store: ReportingStore) -> int:
    """Undoes the newest `done` turn that changed something, whoever made it; returns its id. Holds the document's
    turn lock while it runs, so it cannot race a turn; the lock row has an empty `before`, so it is never undone."""
    lock = start_turn(kind, doc_id, user_id, "undo")
    try:
        with transaction() as s:
            t = s.scalars(select(m.RefineTurn).where(
                m.RefineTurn.kind == kind, m.RefineTurn.doc_id == doc_id, m.RefineTurn.status == "done",
                m.RefineTurn.before != text("'{}'::jsonb"),
            ).order_by(m.RefineTurn.id.desc()).limit(1).with_for_update()).first()
            if t is None:
                raise UndoRefused(NOTHING_TO_UNDO)
            if kind == "rfp":
                qs = {str(q.id): q for q in s.scalars(select(m.RfpQuestion).where(
                    m.RfpQuestion.id.in_([int(k) for k in t.after])).with_for_update())}
                for k in sorted(t.after, key=int):
                    if k not in qs or _state(qs[k]) != t.after[k]:
                        raise UndoRefused(_CONFLICT.format(f"Q{k}"))
                for k, v in t.before.items():
                    for field, value in v.items():
                        setattr(qs[k], field, value)
            else:
                deck = store.load_deck(doc_id)
                current = deck.model_dump(mode="json") if deck else {"slides": []}
                if current != t.after:
                    raise UndoRefused(_CONFLICT.format(f"Slide {_first_changed_slide(current['slides'], t.after['slides'])}"))
                store.save_deck(doc_id, Deck.model_validate(t.before))
                manifest = store.load_manifest(doc_id)
                if manifest is not None:
                    manifest.deck_edited_since_render = True
                    store.save_manifest(manifest)
            t.status, t.undone_at = "undone", datetime.now(UTC)
            return t.id
    finally:
        finish_turn(lock, "done")
