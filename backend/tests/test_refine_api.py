"""refine-chat Turn API, undo and the deck read routes, over HTTP with the stand-in model (AC-1..AC-59 API rows)."""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from arp.api.auth import Principal, authorize, current_user
from arp.api.deps import get_reporting_store
from arp.api.main import app
from arp.config import get_settings
from arp.db import models as m
from arp.db.session import transaction
from arp.rfp import store as rfp_store
from arp.rfp.draft import Cited, DraftOut
from arp.schemas.reporting import (
    ChartSpec,
    DatasetColumn,
    Deck,
    Finding,
    OutputFormat,
    QuantitativeDataset,
    ReportManifest,
    ReportRequest,
    SlideContent,
    Storyline,
    StorylineSlide,
)
from arp.storage.reporting_store import ReportingStore

TODAY = date(2026, 11, 14)
USERS = {n: Principal(user_id=n, name=n, role=r) for n, r in
         [("alice", "analyst"), ("bob", "approver"), ("carol", "approver"), ("vic", "viewer")]}
BUSY = "A change is already running on this document."
VIEWERS = "Viewers cannot change documents."
NO_DECK = "This report has no deck yet. Approve its storyline in Report Builder first."
GROUNDED = "We screen holdings quarterly."
LIB = "We screen all holdings quarterly."


class Env:
    def __init__(self, client, who, folder, reports):
        self.client, self.who, self.folder, self.reports = client, who, folder, reports

    def as_(self, name):
        self.who["user"] = USERS[name]
        return self.client

    def stand_in(self, name, entry):
        (self.folder / "model" / f"{name}.json").write_text(json.dumps(entry))

    def ops(self, ops, reply="ok", **extra):
        self.stand_in("RefineOps", {"output": {"reply": reply, "ops": ops}, **extra})

    def model_calls(self):
        path = self.folder / "calls.jsonl"
        return [c for c in map(json.loads, path.read_text().splitlines()) if c["kind"] == "model"] if path.exists() else []

    def turn(self, kind, doc_id, message="m", user="alice", history=()):
        r = self.as_(user).post(f"/api/refine/{kind}/{doc_id}/turns", json={"message": message, "history": list(history)})
        assert r.status_code == 202, r.text
        return r.json()["turn_id"]

    def get_turn(self, tid):
        return self.as_("alice").get(f"/api/refine/turns/{tid}").json()

    def wait(self, tid, timeout=20.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            out = self.get_turn(tid)
            if out["status"] != "running":
                return out
            time.sleep(0.05)
        raise AssertionError(f"turn {tid} still running")

    def undo(self, kind, doc_id, user="alice"):
        return self.as_(user).post(f"/api/refine/{kind}/{doc_id}/undo")


@pytest.fixture
def env(pg, tmp_path, monkeypatch):
    folder = tmp_path / "standins"
    (folder / "model").mkdir(parents=True)
    monkeypatch.setenv("ARP_STANDINS_DIR", str(folder))
    monkeypatch.delenv("ARP_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ARP_RUNS_DIR", str(tmp_path / "runs"))
    get_settings.cache_clear()
    monkeypatch.setattr(rfp_store, "today", lambda: TODAY)
    who = {"user": USERS["alice"]}
    app.dependency_overrides.pop(authorize, None)  # the real role checks, on the user below
    app.dependency_overrides[current_user] = lambda: who["user"]
    reports = ReportingStore(tmp_path / "reports", tmp_path / "tpl")
    app.dependency_overrides[get_reporting_store] = lambda: reports
    with TestClient(app) as c:  # one event loop for the test, so a background turn keeps running
        yield Env(c, who, folder, reports)
    app.dependency_overrides.pop(current_user, None)
    app.dependency_overrides.pop(get_reporting_store, None)


@pytest.fixture
def P(env):
    """Project P: Q1, Q2 `drafted` (A1, A2), Q3 `approved`, Q4 `no source`; library entry E1. Grounded draft stood in."""
    with transaction() as s:
        e1 = m.RfpLibraryEntry(question="How do you screen holdings?", answer=LIB, tags=[], approved_on=TODAY,
                               review_by=date(2027, 11, 14), has_figures=False)
        p = m.RfpProject(investor="I", filename="rfp.xlsx", content_key="k", run_status="done", created_by="alice")
        s.add_all([e1, p])
        s.flush()
        qs = [m.RfpQuestion(project_id=p.id, position=i, location=f"A{i}", answer_location=f"B{i}", question=f"Question {i}?",
                            answer=a, status=st, flags=[], sources=[])
              for i, (a, st) in enumerate([("A1", "drafted"), ("A2", "drafted"), ("A3", "approved"), ("", "no source")], 1)]
        s.add_all(qs)
        s.flush()
        ids = {"pid": str(p.id), "e1": e1.id, **{f"q{i}": q.id for i, q in enumerate(qs, 1)}}
    draft = DraftOut(answer=GROUNDED, citations=[Cited(entry_id=ids["e1"], quote=LIB)])
    env.stand_in("DraftOut", {"output": draft.model_dump()})
    env.stand_in("FactCheck", {"output": {}})  # the second model's check finds nothing unsupported
    return ids


def state(qid):
    with transaction() as s:
        q = s.get(m.RfpQuestion, qid)
        return {"answer": q.answer, "status": q.status, "sources": q.sources, "flags": q.flags, "last_editor": q.last_editor}


def rows(kind=None):
    with transaction() as s:
        q = select(m.RefineTurn).order_by(m.RefineTurn.id)
        if kind:
            q = q.where(m.RefineTurn.kind == kind)
        ts = list(s.scalars(q))
        return [{"id": t.id, "user_id": t.user_id, "kind": t.kind, "message": t.message, "ops": t.ops, "before": t.before,
                 "status": t.status} for t in ts]


DS = QuantitativeDataset(dataset_id="ds_em", name="Emissions", columns=[DatasetColumn(name="year"), DatasetColumn(name="t")],
                         rows=[{"year": "2023", "t": 10}, {"year": "2024", "t": 8}])


def _deck(chart_dataset="ds_em"):
    return Deck(title="R", slides=[
        SlideContent(headline="One", layout="bullets", variant="three", slots={"items": ["x"]}),
        SlideContent(headline="Two", layout="two_column", variant="text_chart", slots={"text": "old"},
                     chart=ChartSpec(dataset_id=chart_dataset, chart_type="line", category_column="year", value_columns=["t"])),
    ])


@pytest.fixture
def R(env):
    """Report R: a house deck; slide 2 two_column/text_chart with slots `text` and `chart`; no `73` anywhere."""
    return _report(env.reports, _deck())


def _report(store, deck=None):
    man = ReportManifest(title="R", output_format=OutputFormat.HOUSE_DECK)
    store.save_manifest(man)
    store.save_request(man.report_id, ReportRequest(title="R", qualitative_notes="n", datasets=[DS]))
    store.save_findings(man.report_id, [Finding(slide=1, stage="qa", rule="r", message="Target year 2040.")])
    if deck is not None:
        store.save_deck(man.report_id, deck)
    return man.report_id


SET_TEXT = {"op": "set_text", "slide": 2, "slot": "text", "text": "Net zero by 2040"}


# --- RFP turns ----------------------------------------------------------------------------------


def test_turn_202_then_done(env, P):  # AC-1
    env.ops([{"op": "rewrite", "question_ids": [P["q1"], P["q2"]], "instruction": "shorter"}])
    out = env.wait(env.turn("rfp", P["pid"], "shorter"))
    assert (out["status"], out["changed"], out["not_changed"]) == ("done", [P["q1"], P["q2"]], [])
    assert state(P["q1"]) == {"answer": GROUNDED, "status": "drafted", "sources": state(P["q1"])["sources"], "flags": [],
                              "last_editor": None}
    assert [s["entry_id"] for s in state(P["q1"])["sources"]] == [P["e1"]]


def test_progress_while_running(env, P):  # AC-10
    draft = DraftOut(answer=GROUNDED, citations=[Cited(entry_id=P["e1"], quote=LIB)])
    env.stand_in("DraftOut", {"output": draft.model_dump(), "delay_seconds": 2})
    env.ops([{"op": "rewrite", "question_ids": [P["q1"], P["q2"]]}])
    tid = env.turn("rfp", P["pid"])
    time.sleep(1)
    out = env.get_turn(tid)
    assert out["status"] == "running" and out["done"] in (0, 1) and out["total"] == 2
    env.wait(tid)


def test_second_turn_409(env, P):  # AC-11
    env.ops([], delay_seconds=2)
    tid = env.turn("rfp", P["pid"])
    r = env.as_("alice").post(f"/api/refine/rfp/{P['pid']}/turns", json={"message": "again", "history": []})
    assert (r.status_code, r.json()["detail"]) == (409, BUSY)
    env.wait(tid)


def test_viewer_403(env, P):  # AC-12
    r = env.as_("vic").post(f"/api/refine/rfp/{P['pid']}/turns", json={"message": "m", "history": []})
    assert (r.status_code, r.json()["detail"]) == (403, VIEWERS)
    assert rows() == []


def test_turn_log_row(env, P):  # AC-9
    before = {str(P["q1"]): state(P["q1"]), str(P["q2"]): state(P["q2"])}
    ops = [{"op": "rewrite", "question_ids": [P["q1"], P["q2"]], "instruction": "shorter"}]
    env.ops(ops)
    env.wait(env.turn("rfp", P["pid"], "make Q1 and Q2 shorter"))
    [r] = rows()
    assert (r["user_id"], r["kind"], r["message"], r["ops"], r["before"]) == ("alice", "rfp", "make Q1 and Q2 shorter", ops, before)


def test_history_longer_than_five_accepted(env, P):  # spec: no 422 for longer history lists
    env.ops([])
    history = [{"message": f"ask-{i}", "reply": f"answer-{i}"} for i in range(1, 8)] + [{"message": "unanswered", "reply": ""}]
    assert env.wait(env.turn("rfp", P["pid"], history=history))["status"] == "done"
    prompt = env.model_calls()[0]["prompt"]
    assert "ask-7" in prompt and "ask-2" not in prompt and "unanswered" not in prompt


def test_four_eyes_after_chat(env, P):  # AC-8
    env.as_("bob").put(f"/api/rfp/projects/{P['pid']}/questions/{P['q1']}", json={"answer": "bob's words"})
    assert state(P["q1"])["last_editor"] == "bob"
    env.ops([{"op": "rewrite", "question_ids": [P["q1"]]}])
    assert env.wait(env.turn("rfp", P["pid"], user="bob"))["changed"] == [P["q1"]]
    r = env.as_("bob").post(f"/api/rfp/projects/{P['pid']}/questions/{P['q1']}/approve", json={"confirmed_flags": []})
    assert r.status_code == 200, r.text


def test_manual_edit_four_eyes_unchanged(env, P):  # AC-46
    env.as_("bob").put(f"/api/rfp/projects/{P['pid']}/questions/{P['q1']}", json={"answer": "bob's words"})
    r = env.as_("bob").post(f"/api/rfp/projects/{P['pid']}/questions/{P['q1']}/approve",
                            json={"confirmed_flags": state(P["q1"])["flags"]})
    assert (r.status_code, r.json()["detail"]) == (403, "You edited this answer last; another approver must approve it.")


def test_turn_finishes_without_client(env, P):  # Review Focus 5
    env.ops([{"op": "rewrite", "question_ids": [P["q1"]]}], delay_seconds=1)
    tid = env.turn("rfp", P["pid"])
    env.client.close()  # the tab is closed; the turn runs on in the server
    reopened = TestClient(app)
    end = time.monotonic() + 20
    while (out := reopened.get(f"/api/refine/turns/{tid}").json())["status"] == "running" and time.monotonic() < end:
        time.sleep(0.05)
    assert (out["status"], out["changed"]) == ("done", [P["q1"]])


# --- RFP undo -----------------------------------------------------------------------------------


def test_undo_restores(env, P):  # AC-14
    before = state(P["q1"]), state(P["q2"])
    env.ops([{"op": "rewrite", "question_ids": [P["q1"], P["q2"]]}])
    tid = env.wait(env.turn("rfp", P["pid"]))["id"]
    r = env.undo("rfp", P["pid"])
    assert r.status_code == 200, r.text
    assert (r.json()["id"], r.json()["status"]) == (tid, "undone")
    assert (state(P["q1"]), state(P["q2"])) == before


def test_undo_twice(env, P):  # AC-15
    before = state(P["q1"]), state(P["q2"])
    for q in ("q1", "q2"):
        env.ops([{"op": "rewrite", "question_ids": [P[q]]}])
        env.wait(env.turn("rfp", P["pid"]))
    assert env.undo("rfp", P["pid"]).status_code == 200
    assert state(P["q1"])["answer"] == GROUNDED and state(P["q2"]) == before[1]
    assert env.undo("rfp", P["pid"]).status_code == 200
    assert (state(P["q1"]), state(P["q2"])) == before


def test_nothing_to_undo(env, P):  # AC-16; a turn that changed nothing is skipped (Review Focus 3)
    env.ops([])
    env.wait(env.turn("rfp", P["pid"]))
    r = env.undo("rfp", P["pid"])
    assert (r.status_code, r.json()["detail"]) == (409, "Nothing to undo.")


def _turn_then_hand_edit(env, P):
    env.ops([{"op": "rewrite", "question_ids": [P["q1"], P["q2"]]}])
    tid = env.wait(env.turn("rfp", P["pid"]))["id"]
    env.as_("bob").put(f"/api/rfp/projects/{P['pid']}/questions/{P['q1']}", json={"answer": "by hand"})
    return tid


def test_undo_conflict_409(env, P):  # AC-17
    _turn_then_hand_edit(env, P)
    r = env.undo("rfp", P["pid"])
    assert (r.status_code, r.json()["detail"]) == (409, f"Q{P['q1']} changed after this turn; undo would overwrite it.")


def test_undo_conflict_changes_nothing(env, P):  # AC-18
    tid = _turn_then_hand_edit(env, P)
    env.undo("rfp", P["pid"])
    assert state(P["q1"])["answer"] == "by hand" and state(P["q2"])["answer"] == GROUNDED
    assert env.get_turn(tid)["status"] == "done"


def test_viewer_undo_403(env, P):  # AC-54
    env.ops([{"op": "rewrite", "question_ids": [P["q1"]]}])
    env.wait(env.turn("rfp", P["pid"]))
    r = env.undo("rfp", P["pid"], user="vic")
    assert (r.status_code, r.json()["detail"]) == (403, VIEWERS)
    assert state(P["q1"])["answer"] == GROUNDED


# --- deck ---------------------------------------------------------------------------------------


def test_deck_get_and_html(env, R):  # AC-19, AC-20
    env.ops([SET_TEXT])
    assert env.wait(env.turn("deck", R))["changed"] == [2]
    assert env.client.get(f"/api/reports/{R}/deck").json()["slides"][1]["slots"]["text"] == "Net zero by 2040"
    r = env.client.get(f"/api/reports/{R}/deck/html")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "Net zero by 2040" in r.text


def test_deck_turn_log(env, R):  # AC-28
    prior = env.reports.load_deck(R).model_dump(mode="json")
    env.ops([SET_TEXT])
    env.wait(env.turn("deck", R))
    [r] = rows()
    assert (r["kind"], r["before"]) == ("deck", prior)


def test_deck_undo(env, R):  # AC-29
    prior = env.client.get(f"/api/reports/{R}/deck").json()
    env.ops([SET_TEXT])
    env.wait(env.turn("deck", R))
    assert env.undo("deck", R).status_code == 200
    assert env.client.get(f"/api/reports/{R}/deck").json() == prior


def test_deck_undo_conflict_names_slide(env, R):
    env.ops([SET_TEXT])
    env.wait(env.turn("deck", R))
    deck = env.reports.load_deck(R)
    deck.slides[1].headline = "Changed elsewhere"
    env.reports.save_deck(R, deck)
    r = env.undo("deck", R)
    assert (r.status_code, r.json()["detail"]) == (409, "Slide 2 changed after this turn; undo would overwrite it.")
    assert env.reports.load_deck(R) == deck


def test_no_deck_409(env):  # AC-30
    rid = _report(env.reports)
    r = env.as_("alice").post(f"/api/refine/deck/{rid}/turns", json={"message": "m", "history": []})
    assert (r.status_code, r.json()["detail"]) == (409, NO_DECK)
    assert rows() == []
    for path in ("deck", "deck/html"):
        r = env.client.get(f"/api/reports/{rid}/{path}")
        assert (r.status_code, r.json()["detail"]) == (409, NO_DECK)


def test_render_no_model_and_clears_flag(env, R):  # AC-32
    env.ops([SET_TEXT])
    env.wait(env.turn("deck", R))
    assert env.reports.load_manifest(R).deck_edited_since_render is True
    calls = len(env.model_calls())
    r = env.as_("alice").post(f"/api/reports/{R}/render")
    assert r.status_code == 200, r.text
    assert len(env.model_calls()) == calls
    assert env.reports.load_manifest(R).deck_edited_since_render is False


def test_deck_undo_sets_flag(env, R):  # AC-55
    env.ops([SET_TEXT])
    env.wait(env.turn("deck", R))
    assert env.as_("alice").post(f"/api/reports/{R}/render").status_code == 200
    assert env.reports.load_manifest(R).deck_edited_since_render is False
    assert env.undo("deck", R).status_code == 200
    assert env.reports.load_manifest(R).deck_edited_since_render is True


def test_has_deck_in_list(env, R):  # AC-59
    bare = _report(env.reports)
    assert env.as_("alice").post(f"/api/reports/{R}/render").status_code == 200
    reports = {r["report_id"]: r for r in env.client.get("/api/reports").json()["reports"]}
    assert reports[R]["has_deck"] is True and reports[bare]["has_deck"] is False


def test_html_with_missing_dataset_200(env):  # Review Focus 4
    rid = _report(env.reports, _deck(chart_dataset="ds_deleted"))
    r = env.client.get(f"/api/reports/{rid}/deck/html")
    assert r.status_code == 200 and "Two" in r.text


def test_approved_storyline_put_409(env, R):  # AC-47
    storyline = Storyline(title="R", slides=[StorylineSlide(headline="One", purpose="p")], approved=True)
    env.reports.save_storyline(R, storyline)
    r = env.as_("alice").put(f"/api/reports/{R}/storyline", json=storyline.model_dump(mode="json"))
    assert (r.status_code, r.json()["detail"]) == (409, "Storyline already approved")


def test_stale_running_turn_reaped_on_new_turn(env, P):  # spec: `running` for more than 10 minutes -> failed/interrupted
    with transaction() as s:
        old = m.RefineTurn(kind="rfp", doc_id=P["pid"], user_id="alice", message="m",
                           created_at=datetime.now(UTC) - timedelta(minutes=11),
                           updated_at=datetime.now(UTC) - timedelta(minutes=11))
        s.add(old)
        s.flush()
        old_id = old.id
    env.ops([])
    env.wait(env.turn("rfp", P["pid"]))
    out = env.get_turn(old_id)
    assert (out["status"], out["error"]) == ("failed", "interrupted")


def test_undo_while_running_409(env, P):
    env.ops([], delay_seconds=2)
    tid = env.turn("rfp", P["pid"])
    r = env.undo("rfp", P["pid"])
    assert (r.status_code, r.json()["detail"]) == (409, BUSY)
    env.wait(tid)


def test_other_analyst_undoes_alices_turn(env, P, monkeypatch):
    monkeypatch.setitem(USERS, "dan", Principal(user_id="dan", name="dan", role="analyst"))
    before = state(P["q1"])
    env.ops([{"op": "rewrite", "question_ids": [P["q1"]]}])
    env.wait(env.turn("rfp", P["pid"], user="alice"))
    r = env.undo("rfp", P["pid"], user="dan")
    assert r.status_code == 200, r.text
    assert state(P["q1"]) == before


def test_changed_shows_mid_turn(env, P):  # AC-41: the first saved question is in `changed` while the turn runs
    env.ops([{"op": "rewrite", "question_ids": [P["q1"], P["q2"]]}])
    draft = DraftOut(answer=GROUNDED, citations=[Cited(entry_id=P["e1"], quote=LIB)])
    env.stand_in("DraftOut", {"output": draft.model_dump(), "delay_seconds": 1})
    tid = env.turn("rfp", P["pid"])
    end = time.monotonic() + 10
    while (out := env.get_turn(tid))["done"] < 1 and time.monotonic() < end:
        time.sleep(0.05)
    assert (out["status"], out["changed"], out["not_changed"]) == ("running", [P["q1"]], [])
    assert env.wait(tid)["changed"] == [P["q1"], P["q2"]]


def test_turn_with_recent_progress_not_reaped(env, P):  # the timeout counts from the last progress write
    with transaction() as s:
        t = m.RefineTurn(kind="rfp", doc_id=P["pid"], user_id="alice", message="m",
                         created_at=datetime.now(UTC) - timedelta(minutes=11), updated_at=datetime.now(UTC))
        s.add(t)
        s.flush()
        tid = t.id
    r = env.as_("alice").post(f"/api/refine/rfp/{P['pid']}/turns", json={"message": "m", "history": []})
    assert (r.status_code, r.json()["detail"]) == (409, BUSY)
    assert env.get_turn(tid)["status"] == "running"


def test_failed_turn_that_saved_is_undoable(env, P):  # a turn that saved Q1 and then failed
    before = state(P["q1"])
    env.ops([{"op": "rewrite", "question_ids": [P["q1"]]}])
    tid = env.wait(env.turn("rfp", P["pid"]))["id"]
    with transaction() as s:
        s.get(m.RefineTurn, tid).status = "failed"
    r = env.undo("rfp", P["pid"])
    assert (r.status_code, r.json()["id"], r.json()["status"]) == (200, tid, "undone")
    assert state(P["q1"]) == before


@pytest.mark.parametrize("rid", ["nope", ".hidden"])
def test_unknown_or_bad_deck_id_404(env, rid):
    r = env.as_("alice").post(f"/api/refine/deck/{rid}/turns", json={"message": "m", "history": []})
    assert (r.status_code, r.json()["detail"]) == (404, "Report not found")
    assert not (env.reports.reports_dir / rid).exists()
    assert rows() == []
