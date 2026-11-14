"""Refine chat, RFP operations: the model's `rewrite` and `leave_blank` ops, applied one question at a time in id order.
A rewrite goes through the grounded drafting; an answer the library does not back is never saved."""

from __future__ import annotations

import logging
from datetime import date

from arp.db import models as m
from arp.db.session import transaction
from arp.llm.base import LLMClient
from arp.refine.turns import save_progress
from arp.rfp import store
from arp.rfp.draft import APPROVED, DRAFTED, LEFT_BLANK, NO_SOURCE, draft_answer

log = logging.getLogger(__name__)

REWRITE, LEAVE_BLANK = "rewrite", "leave_blank"
NO_SUCH_QUESTION, NOT_BACKED, DRAFT_FAILED = "no such question", "not backed by the library", "draft failed"
USE_AUTOFILL = "no source; use Auto-fill on RFP Answers"
CHANGED_DURING_TURN = "changed during this turn"


def question_state(q: m.RfpQuestion) -> dict:
    return {"answer": q.answer, "status": q.status, "sources": q.sources, "flags": q.flags, "last_editor": q.last_editor}


async def _apply(qid: int, op: dict, project_id: int, entries, llm: LLMClient, today: date, settings):
    """`(before, after)` when the question changed, else the reason it did not."""
    with transaction() as s:
        q = s.get(m.RfpQuestion, qid, with_for_update=True)
        if q is None or q.project_id != project_id:
            return NO_SUCH_QUESTION
        if q.status == APPROVED:
            return APPROVED
        if op["op"] == LEAVE_BLANK:  # the leave-blank endpoint's state change
            before = question_state(q)
            q.status = LEFT_BLANK
            return before, question_state(q)
        if q.status == NO_SOURCE:
            return USE_AUTOFILL
        question, current, read = q.question, q.answer, (q.answer, q.status, q.last_editor)
    try:
        d = await draft_answer(question, entries, llm, today=today, settings=settings,
                               instruction=op.get("instruction"), current=current)
    except Exception:
        log.exception("refine: drafting question %s failed", qid)
        return DRAFT_FAILED
    if d.status == NO_SOURCE:
        return NOT_BACKED
    with transaction() as s:
        q = s.get(m.RfpQuestion, qid, with_for_update=True)
        if (q.answer, q.status, q.last_editor) != read:  # a person's edit or approval while drafting wins
            return CHANGED_DURING_TURN
        before = question_state(q)
        q.answer, q.status, q.sources, q.flags, q.last_editor = d.answer, DRAFTED, d.sources, d.flags, None
        return before, question_state(q)


async def apply_rfp_ops(turn_id: int, project_id: int, ops: list[dict], llm: LLMClient, *, today: date,
                        settings=None) -> dict:
    changed: list[int] = []
    not_changed: list[dict] = []
    before: dict[str, dict] = {}
    after: dict[str, dict] = {}
    todo: dict[int, dict] = {}  # question id -> its first op
    for op in ops:
        if op.get("op") not in (REWRITE, LEAVE_BLANK):
            continue
        if not op.get("question_ids"):
            not_changed.append({"id": None, "reason": NO_SUCH_QUESTION})
        for qid in op.get("question_ids") or []:
            todo.setdefault(qid, op)
    with transaction() as s:
        entries = store._active_entries(s)
    save_progress(turn_id, done=0, total=len(todo))
    for done, qid in enumerate(sorted(todo), 1):
        out = await _apply(qid, todo[qid], project_id, entries, llm, today, settings)
        if isinstance(out, str):
            not_changed.append({"id": qid, "reason": out})
        else:
            changed.append(qid)
            before[str(qid)], after[str(qid)] = out
        save_progress(turn_id, done=done, before=before, after=after)  # saved so far stays undoable if the turn dies
    return {"changed": changed, "not_changed": not_changed, "before": before, "after": after}
