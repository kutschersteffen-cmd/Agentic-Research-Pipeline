"""refine-chat "Turn API": the prompt, the one model call and the turn's orchestration (AC-13), RFP and deck."""

from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest
from sqlalchemy import select

from arp.db import models as m
from arp.db.session import transaction
from arp.refine import turns
from arp.refine.agent import run_turn
from arp.rfp.draft import Cited, DraftOut
from arp.schemas.reporting import Deck, Finding, ReportManifest, ReportRequest, SlideContent
from arp.standins import StandInLLMClient
from arp.storage.reporting_store import ReportingStore

TODAY = date(2026, 11, 14)


@pytest.fixture
def llm(tmp_path):
    (tmp_path / "standins" / "model").mkdir(parents=True)
    return StandInLLMClient(tmp_path / "standins")


def stand_in(llm, entry):
    (llm._folder / "model" / "RefineOps.json").write_text(json.dumps(entry))


def model_calls(llm):
    path = llm._folder / "calls.jsonl"
    lines = path.read_text().splitlines() if path.exists() else []
    return [c for c in map(json.loads, lines) if c["kind"] == "model"]


@pytest.fixture
def project(pg):
    """Project P with Q1 (`drafted`, answer `A1`)."""
    with transaction() as s:
        p = m.RfpProject(investor="I", filename="rfp.xlsx", content_key="k", run_status="done", created_by="alice")
        s.add(p)
        s.flush()
        s.add(m.RfpQuestion(project_id=p.id, position=1, location="A1", answer_location="B1",
                            question="How often do you screen holdings?", answer="A1", status="drafted", flags=[], sources=[]))
        return str(p.id)


def row(tid):
    with transaction() as s:
        t = s.execute(select(m.RefineTurn).where(m.RefineTurn.id == tid)).scalar_one()
        return {"status": t.status, "error": t.error, "ops": t.ops, "before": t.before, "after": t.after, "result": t.result}


def rfp_turn(pid, llm, message="m", history=()):
    tid = turns.start_turn("rfp", pid, "alice", message)
    asyncio.run(run_turn(tid, "rfp", pid, message, list(history), llm, None, today=TODAY))
    return tid


def test_history_keeps_last_five(llm, project):  # AC-13
    stand_in(llm, {"output": {"reply": "ok", "ops": []}})
    history = [{"message": f"ask-{i}", "reply": f"answer-{i}"} for i in range(1, 8)]
    rfp_turn(project, llm, history=history)
    prompt = model_calls(llm)[0]["prompt"]
    for i in range(3, 8):
        assert f"ask-{i}" in prompt and f"answer-{i}" in prompt
    for i in (1, 2):
        assert f"ask-{i}" not in prompt and f"answer-{i}" not in prompt


def test_large_rfp_refused_without_model_call(pg, llm):
    with transaction() as s:
        p = m.RfpProject(investor="I", filename="rfp.xlsx", content_key="k", run_status="done", created_by="alice")
        s.add(p)
        s.flush()
        s.add_all([m.RfpQuestion(project_id=p.id, position=i, location=f"A{i}", answer_location=f"B{i}", question=f"q{i}",
                                 answer="a", status="drafted", flags=[], sources=[]) for i in range(401)])
        pid = str(p.id)
    tid = turns.start_turn("rfp", pid, "alice", "shorter")
    asyncio.run(run_turn(tid, "rfp", pid, "shorter", [], llm, None, today=TODAY))
    assert model_calls(llm) == []
    out = turns.turn_out(tid)
    assert out["status"] == "done"
    assert out["reply"] == "This RFP has more than 400 questions. Name a section or question numbers."
    assert out["changed"] == []


def test_model_failure_changes_nothing(llm, project):
    stand_in(llm, {"error": "model down"})
    tid = rfp_turn(project, llm)
    r = row(tid)
    assert (r["status"], r["error"]) == ("failed", "model down")
    assert (r["ops"], r["before"], r["after"], r["result"]) == ([], {}, {}, {})
    with transaction() as s:
        assert [q.answer for q in s.scalars(select(m.RfpQuestion).where(m.RfpQuestion.project_id == int(project)))] == ["A1"]


def test_empty_ops_done_and_not_undoable_marker(llm, project):
    stand_in(llm, {"output": {"reply": "Nothing to change.", "ops": []}})
    tid = rfp_turn(project, llm)
    r = row(tid)
    assert r["status"] == "done" and r["before"] == {} and r["result"]["changed"] == []
    assert r["result"]["reply"] == "Nothing to change."


def test_rfp_rewrite_end_to_end(pg, llm):
    with transaction() as s:
        e1 = m.RfpLibraryEntry(question="How do you screen holdings?", answer="We screen all holdings quarterly.", tags=[],
                               approved_on=TODAY, review_by=date(2027, 11, 14), has_figures=False)
        p = m.RfpProject(investor="I", filename="rfp.xlsx", content_key="k", run_status="done", created_by="alice")
        s.add_all([e1, p])
        s.flush()
        q1 = m.RfpQuestion(project_id=p.id, position=1, location="A1", answer_location="B1",
                           question="How often do you screen holdings?", answer="A1", status="drafted", flags=[], sources=[])
        s.add(q1)
        s.flush()
        pid, qid, eid = str(p.id), q1.id, e1.id
    stand_in(llm, {"output": {"reply": "Shortening Q1.", "ops": [{"op": "rewrite", "question_ids": [qid], "instruction": "shorter"}]}})
    draft = DraftOut(answer="We screen holdings quarterly.", citations=[Cited(entry_id=eid, quote="We screen all holdings quarterly.")])
    (llm._folder / "model" / "DraftOut.json").write_text(json.dumps({"output": draft.model_dump()}))
    (llm._folder / "model" / "FactCheck.json").write_text(json.dumps({"output": {}}))  # the second model's check passes
    tid = turns.start_turn("rfp", pid, "alice", "shorter")
    asyncio.run(run_turn(tid, "rfp", pid, "shorter", [], llm, None, today=TODAY))
    out = turns.turn_out(tid)
    assert (out["status"], out["reply"], out["changed"], out["not_changed"]) == ("done", "Shortening Q1.", [qid], [])
    with transaction() as s:
        assert s.get(m.RfpQuestion, qid).answer == "We screen holdings quarterly."
    assert row(tid)["before"][str(qid)]["answer"] == "A1"


def test_reaped_turn_writes_no_answer(llm, project):
    with transaction() as s:
        qid = s.scalars(select(m.RfpQuestion.id).where(m.RfpQuestion.project_id == int(project))).one()
    stand_in(llm, {"output": {"reply": "Done.", "ops": [{"op": "rewrite", "question_ids": [qid]}]}})

    class ReapsDuringCall:
        async def complete_structured(self, **kw):
            turns.reap_stale_turns()  # the turn times out during the model call
            return await llm.complete_structured(**kw)

    tid = rfp_turn(project, ReapsDuringCall())
    assert row(tid)["status"] == "failed"
    with transaction() as s:
        assert s.get(m.RfpQuestion, qid).answer == "A1"


# --- deck turns (slice 2) -----------------------------------------------------------------------


@pytest.fixture
def report(tmp_path):
    """Report R: slide 2 is two_column/text_chart with slot `text`; nothing in it contains a 73."""
    store = ReportingStore(tmp_path / "reports", tmp_path / "tpl")
    man = ReportManifest(title="R")
    store.save_manifest(man)
    store.save_request(man.report_id, ReportRequest(title="R", qualitative_notes="n"))
    store.save_findings(man.report_id, [Finding(slide=1, stage="qa", rule="r", message="Target year 2040.")])
    store.save_deck(man.report_id, Deck(title="R", slides=[
        SlideContent(headline="One", layout="bullets", variant="three", slots={"items": ["x"]}),
        SlideContent(headline="Two", layout="two_column", variant="text_chart", slots={"text": "old"}),
    ]))
    return store, man.report_id


def deck_turn(store, rid, llm, message="m", history=()):
    tid = turns.start_turn("deck", rid, "alice", message)
    asyncio.run(run_turn(tid, "deck", rid, message, list(history), llm, store, today=TODAY))
    return tid


def test_deck_turn_logs_and_sets_edited_flag(pg, llm, report):  # AC-28, AC-31
    store, rid = report
    deck_before = store.load_deck(rid)
    op = {"op": "set_text", "slide": 2, "slot": "text", "text": "Net zero by 2040"}
    stand_in(llm, {"output": {"reply": "Done.", "ops": [op]}})
    tid = deck_turn(store, rid, llm)
    assert store.load_deck(rid).slides[1].slots["text"] == "Net zero by 2040"
    assert store.load_manifest(rid).deck_edited_since_render is True
    r = row(tid)
    assert r["status"] == "done" and r["ops"] == [op]
    assert r["before"] == deck_before.model_dump(mode="json")
    assert r["after"] == store.load_deck(rid).model_dump(mode="json")
    assert r["result"] == {"reply": "Done.", "changed": [2], "not_changed": [], "check_figures": []}  # 2040 is in the findings


def test_deck_turn_with_no_change_leaves_flag_and_undo_marker(pg, llm, report):
    store, rid = report
    stand_in(llm, {"output": {"reply": "Nothing to change.", "ops": []}})
    r = row(deck_turn(store, rid, llm))
    assert r["status"] == "done" and r["before"] == {} and r["result"]["changed"] == []
    assert store.load_manifest(rid).deck_edited_since_render is False


def test_deck_prompt_lists_slides_and_allowed_slots(pg, llm, report):
    store, rid = report
    stand_in(llm, {"output": {"reply": "ok", "ops": []}})
    deck_turn(store, rid, llm, message="make slide 2 shorter")
    [call] = model_calls(llm)
    prompt = json.dumps(call)
    assert "make slide 2 shorter" in prompt and "text_chart" in prompt and "allowed_variants_and_slots" in prompt


def test_reaped_deck_turn_writes_no_deck(pg, llm, report):
    store, rid = report
    deck_before = store.load_deck(rid)
    stand_in(llm, {"output": {"reply": "Done.", "ops": [{"op": "set_text", "slide": 2, "slot": "text", "text": "New"}]}})

    class ReapsDuringCall:
        async def complete_structured(self, **kw):
            turns.reap_stale_turns()  # the turn times out during the model call
            return await llm.complete_structured(**kw)

    tid = deck_turn(store, rid, ReapsDuringCall())
    assert store.load_deck(rid) == deck_before and row(tid)["status"] == "failed"
