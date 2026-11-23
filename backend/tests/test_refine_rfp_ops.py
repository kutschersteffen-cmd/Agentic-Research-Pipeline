"""refine-chat "RFP operations": rewrite and leave_blank, applied one question at a time (AC-1..AC-8, AC-52, AC-58)."""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

from arp.db import models as m
from arp.db.session import transaction
from arp.llm.base import LLMUsage
from arp.refine import turns
from arp.refine.rfp_ops import apply_rfp_ops
from arp.rfp.draft import Cited, DraftOut, FactCheck

TODAY = date(2026, 11, 14)
E1_ANSWER = "We screen all holdings quarterly. Exclusions cover thermal coal."


class Standin:
    """The model: every `DraftOut` call returns `draft` (or raises it), or `per_question[question]` when given."""

    def __init__(self, draft=None, per_question=None):
        self.draft, self.per_question, self.prompts = draft, per_question or {}, []

    async def complete_structured(self, *, system, prompt, output_model, **_):
        assert output_model is DraftOut
        self.prompts.append(prompt)
        out = self.per_question.get(prompt.split("RFP question: ", 1)[1].split("\n", 1)[0], self.draft)
        if isinstance(out, Exception):
            raise out
        return out, LLMUsage()


class Passes:
    """The second model: finds nothing unsupported or unanswered."""

    async def complete_structured(self, *, output_model, **_):
        assert output_model is FactCheck
        return FactCheck(), LLMUsage()


@pytest.fixture
def p(pg):
    """The spec's fixture: project P, Q1/Q2 drafted (A1, A2), Q3 approved, Q4 no source, library entry E1."""
    with transaction() as s:
        e1 = m.RfpLibraryEntry(question="How do you screen holdings?", answer=E1_ANSWER, tags=[], approved_on=TODAY,
                               review_by=date(2027, 11, 14), has_figures=False)
        proj = m.RfpProject(investor="Pension Fund", filename="rfp.xlsx", content_key="k", run_status="done",
                            created_by="alice")
        s.add_all([e1, proj])
        s.flush()
        qs = [m.RfpQuestion(project_id=proj.id, position=i, location=f"RFP!A{i}", answer_location=f"RFP!B{i}",
                            question=f"Q{i}: how often do you screen holdings?", answer=a, status=st, flags=[],
                            sources=[{"entry_id": e1.id, "quote": "We screen all holdings quarterly."}] if a else [])
              for i, (a, st) in enumerate([("A1", "drafted"), ("A2", "drafted"), ("A3", "approved"), ("", "no source")], 1)]
        s.add_all(qs)
        s.flush()
        return {"P": proj.id, "E1": e1.id, **{f"Q{i}": q.id for i, q in enumerate(qs, 1)}}


def grounded(p):
    """The spec's grounded draft, citing E1."""
    return DraftOut(answer="We screen holdings quarterly.",
                    citations=[Cited(entry_id=p["E1"], quote="We screen all holdings quarterly.")])


def state(qid):
    with transaction() as s:
        q = s.get(m.RfpQuestion, qid)
        return {"answer": q.answer, "status": q.status, "sources": q.sources, "flags": q.flags,
                "last_editor": q.last_editor}


def run(p, ops, llm):
    tid = turns.start_turn("rfp", str(p["P"]), "alice", "msg")
    return tid, asyncio.run(apply_rfp_ops(tid, p["P"], ops, llm, today=TODAY, verifier=Passes()))


def test_rewrite_two_grounded(p):
    before = {str(p[q]): state(p[q]) for q in ("Q1", "Q2")}
    tid, out = run(p, [{"op": "rewrite", "question_ids": [p["Q2"], p["Q1"]], "instruction": "shorter"}], Standin(grounded(p)))
    assert out["changed"] == [p["Q1"], p["Q2"]]
    assert out["not_changed"] == []
    for q in ("Q1", "Q2"):
        assert state(p[q]) == {"answer": "We screen holdings quarterly.", "status": "drafted",
                               "sources": [{"entry_id": p["E1"], "quote": "We screen all holdings quarterly."}],
                               "flags": [], "last_editor": None}
    assert out["before"] == before
    assert out["after"] == {str(p[q]): state(p[q]) for q in ("Q1", "Q2")}
    t = turns.turn_out(tid)
    assert (t["done"], t["total"]) == (2, 2)


def test_ungrounded_keeps_answer(p):
    before = state(p["Q1"])
    _, out = run(p, [{"op": "rewrite", "question_ids": [p["Q1"]]}], Standin(DraftOut(answer="Something.")))
    assert state(p["Q1"]) == before
    assert (out["changed"], out["not_changed"]) == ([], [{"id": p["Q1"], "reason": "not backed by the library"}])


def test_figure_not_in_source_keeps_answer(p):
    before = state(p["Q1"])
    draft = grounded(p).model_copy(update={"answer": "We screen 42 funds quarterly."})
    _, out = run(p, [{"op": "rewrite", "question_ids": [p["Q1"]]}], Standin(draft))
    assert state(p["Q1"]) == before
    assert out["not_changed"] == [{"id": p["Q1"], "reason": "not backed by the library"}]


def test_approved_untouched(p):
    before = state(p["Q3"])
    llm = Standin(grounded(p))
    _, out = run(p, [{"op": "rewrite", "question_ids": [p["Q3"]]}], llm)
    assert state(p["Q3"]) == before
    assert out["not_changed"] == [{"id": p["Q3"], "reason": "approved"}]
    assert llm.prompts == []


def test_no_source_skipped_without_model_call(p):
    before = state(p["Q4"])
    llm = Standin(grounded(p))
    _, out = run(p, [{"op": "rewrite", "question_ids": [p["Q4"]]}], llm)
    assert state(p["Q4"]) == before
    assert out["not_changed"] == [{"id": p["Q4"], "reason": "no source; use Auto-fill on RFP Answers"}]
    assert llm.prompts == []


def test_leave_blank(p):
    before = state(p["Q1"])
    _, out = run(p, [{"op": "leave_blank", "question_ids": [p["Q1"]]}], Standin())
    assert state(p["Q1"]) == {**before, "status": "left blank"}
    assert out["changed"] == [p["Q1"]]
    assert out["before"] == {str(p["Q1"]): before}


def test_rewrite_edited_clears_last_editor(p):
    """AC-8's precondition: a rewrite of bob's edit leaves `last_editor` null, so bob may approve it."""
    with transaction() as s:
        q = s.get(m.RfpQuestion, p["Q1"])
        q.status, q.last_editor = "edited", "bob"
    _, out = run(p, [{"op": "rewrite", "question_ids": [p["Q1"]]}], Standin(grounded(p)))
    assert out["changed"] == [p["Q1"]]
    assert (state(p["Q1"])["status"], state(p["Q1"])["last_editor"]) == ("drafted", None)


def test_draft_error_continues(p):
    q1 = "Q1: how often do you screen holdings?"
    tid, out = run(p, [{"op": "rewrite", "question_ids": [p["Q1"], p["Q2"]]}],
                   Standin(grounded(p), per_question={q1: RuntimeError("model down")}))
    assert out["changed"] == [p["Q2"]]
    assert out["not_changed"] == [{"id": p["Q1"], "reason": "draft failed"}]
    assert state(p["Q1"])["answer"] == "A1"
    assert turns.turn_out(tid)["done"] == 2


def test_instruction_reaches_draft_prompt(p):  # AC-58
    llm = Standin(grounded(p))
    run(p, [{"op": "rewrite", "question_ids": [p["Q1"]], "instruction": "shorter"}], llm)
    assert "shorter" in llm.prompts[0] and "A1" in llm.prompts[0]
    assert "Style instruction: shorter" in llm.prompts[0] and "Current answer: A1" in llm.prompts[0]


def test_missing_question_ids_is_no_such_question(p):
    _, out = run(p, [{"op": "rewrite", "question_ids": None, "instruction": "x"}, {"op": "rewrite", "question_ids": [999999]}],
                 Standin(grounded(p)))
    assert out["changed"] == []
    assert out["not_changed"] == [{"id": None, "reason": "no such question"}, {"id": 999999, "reason": "no such question"}]


def test_question_of_another_project_is_no_such_question(p):
    with transaction() as s:
        other = m.RfpProject(investor="X", filename="x.xlsx", content_key="k2", run_status="done", created_by="bob")
        s.add(other)
        s.flush()
        s.get(m.RfpQuestion, p["Q1"]).project_id = other.id
    _, out = run(p, [{"op": "rewrite", "question_ids": [p["Q1"]]}], Standin(grounded(p)))
    assert out["not_changed"] == [{"id": p["Q1"], "reason": "no such question"}]


def test_current_answer_is_style_reference_only(p):
    llm = Standin(grounded(p))
    run(p, [{"op": "rewrite", "question_ids": [p["Q1"]]}], llm)
    assert llm.prompts[0].endswith("Current answer: A1\n\nUse the current answer as a style reference only: every "
                                   "statement in your answer must be backed by a quoted library entry.")


def test_hand_edit_during_draft_survives(p):
    class EditsWhileDrafting(Standin):
        async def complete_structured(self, **kw):
            with transaction() as s:  # bob edits Q1 on RFP Answers while its re-draft is being written
                q = s.get(m.RfpQuestion, p["Q1"])
                q.answer, q.status, q.last_editor = "Bob's answer", "edited", "bob"
            return await super().complete_structured(**kw)

    _, out = run(p, [{"op": "rewrite", "question_ids": [p["Q1"]]}], EditsWhileDrafting(grounded(p)))
    assert (state(p["Q1"])["answer"], state(p["Q1"])["status"], state(p["Q1"])["last_editor"]) == (
        "Bob's answer", "edited", "bob")
    assert (out["changed"], out["not_changed"]) == ([], [{"id": p["Q1"], "reason": "changed during this turn"}])
    assert out["before"] == out["after"] == {}


def test_question_deleted_while_drafting_is_no_such_question(p):
    class DeletesWhileDrafting(Standin):
        async def complete_structured(self, **kw):
            if not self.prompts:  # Q1 is deleted while its re-draft is being written
                with transaction() as s:
                    s.delete(s.get(m.RfpQuestion, p["Q1"]))
            return await super().complete_structured(**kw)

    tid, out = run(p, [{"op": "rewrite", "question_ids": [p["Q1"], p["Q2"]]}], DeletesWhileDrafting(grounded(p)))
    assert (out["changed"], out["not_changed"]) == ([p["Q2"]], [{"id": p["Q1"], "reason": "no such question"}])
    assert turns.turn_out(tid)["done"] == 2


def test_progress_lists_changed_so_far(p):
    seen = []

    class Watches(Standin):
        async def complete_structured(self, **kw):
            if self.prompts:  # drafting Q2: Q1 is already saved
                seen.append(turns.turn_out(tid))
            return await super().complete_structured(**kw)

    tid = turns.start_turn("rfp", str(p["P"]), "alice", "msg")
    turns.save_progress(tid, result={"reply": "ok"})
    asyncio.run(apply_rfp_ops(tid, p["P"], [{"op": "rewrite", "question_ids": [p["Q1"], p["Q2"], p["Q3"]]}],
                              Watches(grounded(p)), today=TODAY, verifier=Passes()))
    assert (seen[0]["reply"], seen[0]["changed"], seen[0]["not_changed"]) == ("ok", [p["Q1"]], [])
    t = turns.turn_out(tid)
    assert (t["changed"], t["not_changed"]) == ([p["Q1"], p["Q2"]], [{"id": p["Q3"], "reason": "approved"}])


def test_skips_count_before_drafting(p):
    """AC-41: approved Q3 counts up front, so the count reads 2 of 3 while Q2 drafts, not 1 then straight to 3."""
    seen = []

    class Watches(Standin):
        async def complete_structured(self, **kw):
            seen.append(turns.turn_out(tid))
            return await super().complete_structured(**kw)

    tid = turns.start_turn("rfp", str(p["P"]), "alice", "msg")
    asyncio.run(apply_rfp_ops(tid, p["P"], [{"op": "rewrite", "question_ids": [p["Q1"], p["Q2"], p["Q3"]]}],
                              Watches(grounded(p)), today=TODAY, verifier=Passes()))
    assert [(t["done"], t["total"]) for t in seen] == [(1, 3), (2, 3)]
    assert turns.turn_out(tid)["done"] == 3


def test_reaped_turn_stops_between_questions(p):
    class ReapsWhileDrafting(Standin):
        async def complete_structured(self, **kw):
            turns.reap_stale_turns()  # the turn times out while Q1 is drafted
            return await super().complete_structured(**kw)

    llm = ReapsWhileDrafting(grounded(p))
    _, out = run(p, [{"op": "rewrite", "question_ids": [p["Q1"], p["Q2"]]}], llm)
    assert len(llm.prompts) == 1 and state(p["Q2"])["answer"] == "A2"


def test_reaped_while_drafting_writes_nothing(p):
    class ReapsWhileDrafting(Standin):
        async def complete_structured(self, **kw):
            turns.reap_stale_turns()  # the turn times out while Q1 is drafted
            return await super().complete_structured(**kw)

    run(p, [{"op": "rewrite", "question_ids": [p["Q1"]]}], ReapsWhileDrafting(grounded(p)))
    assert state(p["Q1"])["answer"] == "A1"  # no write without an undo record


def test_leave_blank_on_reaped_turn_writes_nothing(p):  # security review #656, optional 1
    tid = turns.start_turn("rfp", str(p["P"]), "alice", "msg")
    turns.reap_stale_turns()  # reaped during the op-planning model call
    out = asyncio.run(apply_rfp_ops(tid, p["P"], [{"op": "leave_blank", "question_ids": [p["Q1"]]}], Standin(),
                                    today=TODAY, verifier=Passes()))
    assert state(p["Q1"])["status"] == "drafted" and out["changed"] == []


def test_change_logged_with_the_write(p):  # security review #656, optional 1: a reap after a write keeps its undo record
    class ReapsAfterQ1(Standin):
        async def complete_structured(self, **kw):
            if len(self.prompts) == 1:  # Q1 is saved; the turn is reaped while Q2 drafts
                turns.reap_stale_turns()
            return await super().complete_structured(**kw)

    tid, _ = run(p, [{"op": "rewrite", "question_ids": [p["Q1"], p["Q2"]]}], ReapsAfterQ1(grounded(p)))
    with transaction() as s:
        t = s.get(m.RefineTurn, tid)
        assert (t.status, list(t.before), t.before[str(p["Q1"])]["answer"]) == ("failed", [str(p["Q1"])], "A1")
