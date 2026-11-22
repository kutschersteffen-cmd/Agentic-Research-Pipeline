"""refine-chat Turn API, the turn list and undo for RFP documents, over HTTP with the stand-in model (slice 1 API rows)."""

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
from arp.storage.reporting_store import ReportingStore

TODAY = date(2026, 11, 14)
USERS = {n: Principal(user_id=n, name=n, role=r) for n, r in
         [("alice", "analyst"), ("bob", "approver"), ("carol", "approver"), ("vic", "viewer")]}
BUSY = "A change is already running on this document."
VIEWERS = "Viewers cannot change documents."
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


# --- robustness -------------------------------------------------------------------------------


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


# --- turn list and kinds (amendment 2026-11-22) -------------------------------------------------


def test_turn_list_after_turn(env, P):  # AC-60
    env.ops([{"op": "rewrite", "question_ids": [P["q1"], P["q2"]], "instruction": "shorter"}], reply="Shortening Q1 and Q2.")
    tid = env.wait(env.turn("rfp", P["pid"], "make them shorter"))["id"]
    r = env.as_("vic").get(f"/api/refine/rfp/{P['pid']}/turns")  # any signed-in role reads it
    assert r.status_code == 200, r.text
    [t] = r.json()
    assert t["created_at"]
    assert {k: v for k, v in t.items() if k != "created_at"} == {
        "turn_id": tid, "user_id": "alice", "message": "make them shorter", "reply": "Shortening Q1 and Q2.",
        "status": "done", "done": 2, "total": 2, "changed": [P["q1"], P["q2"]], "not_changed": [], "check_figures": [],
        "error": None}


def test_turn_list_empty(env, P):  # AC-60b
    r = env.as_("alice").get(f"/api/refine/rfp/{P['pid']}/turns")
    assert (r.status_code, r.json()) == (200, [])


def test_turn_list_oldest_first_reply_null_while_running_and_no_undo_row(env, P):
    env.ops([{"op": "rewrite", "question_ids": [P["q1"]]}], reply="first")
    first = env.wait(env.turn("rfp", P["pid"], "one"))["id"]
    assert env.undo("rfp", P["pid"]).status_code == 200  # undo's lock row is not a turn
    env.ops([], reply="second", delay_seconds=2)
    second = env.turn("rfp", P["pid"], "two")
    running = env.as_("alice").get(f"/api/refine/rfp/{P['pid']}/turns").json()
    assert [(t["turn_id"], t["status"], t["reply"]) for t in running] == [(first, "undone", "first"), (second, "running", None)]
    env.wait(second)


@pytest.mark.parametrize("kind", ["memo", "deck"])  # AC-60c; `deck` until the deck operations land
@pytest.mark.parametrize("method,path", [("post", "turns"), ("get", "turns"), ("post", "undo")])
def test_unknown_kind_404(env, P, kind, method, path):
    kw = {"json": {"message": "m", "history": []}} if path == "turns" and method == "post" else {}
    r = getattr(env.as_("alice"), method)(f"/api/refine/{kind}/{P['pid']}/{path}", **kw)
    assert (r.status_code, r.json()) == (404, {"detail": "Unknown document kind."})
    assert rows() == []


def test_running_turn_failed_by_api_restart(env, P):  # AC-53
    with transaction() as s:
        t = m.RefineTurn(kind="rfp", doc_id=P["pid"], user_id="alice", message="m")  # left running by a dead process
        s.add(t)
        s.flush()
        tid = t.id
    with TestClient(app):  # the API starts again
        pass
    out = env.get_turn(tid)
    assert (out["status"], out["error"]) == ("failed", "interrupted")
    env.ops([])
    env.wait(env.turn("rfp", P["pid"]))


# --- review fixes (#656 code review, blocking 1 and 2) ---------------------------------------------


def test_undo_restores_base_entry_and_priority(env, P):
    with transaction() as s:
        q = s.get(m.RfpQuestion, P["q1"])
        q.base_entry_id, q.document_priority = None, 2  # Q1 was drafted from a reference document
    env.ops([{"op": "rewrite", "question_ids": [P["q1"]]}])
    env.wait(env.turn("rfp", P["pid"]))
    assert env.undo("rfp", P["pid"]).status_code == 200
    with transaction() as s:
        q = s.get(m.RfpQuestion, P["q1"])
        assert q.answer == "A1"
        assert (q.base_entry_id, q.document_priority) == (None, 2)


def test_undo_of_turn_logged_without_restore(env, P):  # a turn logged before `result["restore"]` was kept
    before = state(P["q1"])
    env.ops([{"op": "rewrite", "question_ids": [P["q1"]]}])
    tid = env.wait(env.turn("rfp", P["pid"]))["id"]
    with transaction() as s:
        t = s.get(m.RefineTurn, tid)
        t.result = {k: v for k, v in t.result.items() if k != "restore"}
    assert env.undo("rfp", P["pid"]).status_code == 200
    assert state(P["q1"]) == before


def test_noncanonical_doc_id_shares_the_lock(env, P):
    env.ops([{"op": "rewrite", "question_ids": [P["q1"]]}], delay_seconds=2)
    t1 = env.turn("rfp", P["pid"])
    r = env.as_("alice").post(f"/api/refine/rfp/0{P['pid']}/turns", json={"message": "m", "history": []})
    env.wait(t1)
    assert (r.status_code, r.json().get("detail")) == (409, BUSY)
    assert [t["turn_id"] for t in env.as_("alice").get(f"/api/refine/rfp/0{P['pid']}/turns").json()] == [t1]


@pytest.mark.parametrize("method,path", [("post", "turns"), ("get", "turns"), ("post", "undo")])
def test_non_ascii_digit_doc_id_404(env, P, method, path):
    kw = {"json": {"message": "m", "history": []}} if (method, path) == ("post", "turns") else {}
    r = getattr(TestClient(app, raise_server_exceptions=False), method)(f"/api/refine/rfp/²/{path}", **kw)
    assert (r.status_code, r.json()["detail"]) == (404, "RFP project not found")
