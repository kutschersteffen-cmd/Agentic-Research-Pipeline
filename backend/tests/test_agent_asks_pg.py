"""Ask threads on the Agent screen (spec agent-panel-code-mode, Phase 7, slice 13)."""
from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arp.api.auth import Principal, authorize, current_user
from arp.api.main import app
from arp.api.routers import plans
from arp.orchestration.ask_store import AskStore
from arp.orchestration.plan_models import AgentAsk
from arp.orchestration.plan_planner import PlanScript
from arp.orchestration.plan_store import PlanStore
from arp.storage.postgres import get_engine
from tests.test_api_ask import ERROR_DETAIL, audit, env, routing, script  # noqa: F401  (env is a fixture)

ZERO = "00000000-0000-0000-0000-000000000000"


def post(env, question, thread_id=None):  # noqa: F811
    body = {"question": question} if thread_id is None else {"question": question, "thread_id": thread_id}
    return env["client"].post("/api/agent/asks", json=body)


def stored(pg) -> int:
    with Session(get_engine(pg)) as s:
        return s.scalar(select(func.count()).select_from(AgentAsk))


def as_viewer():
    app.dependency_overrides.pop(authorize, None)
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u_v", name="Vera", role="viewer")


def test_new_thread_answers_and_stores(env, pg):  # noqa: F811 - AC-68 (unit side)
    script(env, AskRouting=[routing("benchmark_sectors", "Sector weights of MSCI World?")])
    r = post(env, "sector weights of msci world")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["thread_id"] == body["id"]
    assert (body["tool"], body["standalone_question"], body["error"]) == ("benchmark_sectors", "Sector weights of MSCI World?", None)
    assert body["response"]["benchmark_sectors"]["is_sample"] is True
    assert (body["plans"], body["explorations"]) == ([], [])
    assert set(body) == {"id", "thread_id", "question", "standalone_question", "tool", "response", "error", "asked_by",
                         "created_at", "plans", "explorations"}  # AC-72a


def test_follow_up_sends_the_threads_history(env):  # noqa: F811 - AC-68b, AC-72
    script(env, AskRouting=[routing("benchmark_sectors", "Sector weights of MSCI World?"), routing("benchmark_sectors", "top 3")])
    t = post(env, "sector weights of msci world").json()["thread_id"]
    r = post(env, "and only the top 3", t)
    assert r.status_code == 200 and r.json()["thread_id"] == t
    assert "- Sector weights of MSCI World? [benchmark_sectors]" in env["llm"].prompts[-1].splitlines()
    rows = env["client"].get("/api/agent/asks", params={"thread_id": t}).json()
    assert [a["question"] for a in rows] == ["sector weights of msci world", "and only the top 3"]


def test_history_is_the_newest_5_answered_asks(env):  # noqa: F811 - AC-68c
    script(env, AskRouting=[routing("none", f"S{i}") for i in range(1, 8)])
    t = post(env, "q1").json()["thread_id"]
    for i in range(2, 7):
        post(env, f"q{i}", t)
    post(env, "q7", t)
    prompt = env["llm"].prompts[-1]
    positions = [prompt.index(f"- S{i} [none]") for i in range(2, 7)]
    assert positions == sorted(positions) and "S1 [none]" not in prompt


def test_unknown_or_follow_up_thread_is_404(env, pg):  # noqa: F811 - AC-68d, AC-68f, AC-72c, AC-72d
    script(env, AskRouting=[routing("none", "a"), routing("none", "b")])
    t = post(env, "a").json()["thread_id"]
    f = post(env, "b", t).json()["id"]
    before = stored(pg)
    for bad in (ZERO, f, "abc"):
        r = post(env, "x", bad)
        assert (r.status_code, r.json()) == (404, {"detail": "ask thread not found"})
    assert stored(pg) == before
    assert env["client"].get("/api/agent/asks", params={"thread_id": ZERO}).json() == {"detail": "ask thread not found"}
    assert env["client"].get("/api/agent/asks", params={"thread_id": f}).status_code == 404


def test_blank_question_is_422_and_stores_nothing(env, pg):  # noqa: F811 - AC-68e
    assert post(env, "   ").status_code == 422
    assert stored(pg) == 0


def test_failed_ask_is_stored_with_200(env):  # noqa: F811 - AC-69, AC-69b
    r = post(env, "q69")  # nothing scripted for AskRouting: the model call raises
    assert r.status_code == 200
    body = r.json()
    assert (body["tool"], body["standalone_question"], body["response"], body["error"]) == (None, None, None, ERROR_DETAIL)
    assert len(env["client"].get("/api/agent/asks", params={"thread_id": body["id"]}).json()) == 1
    script(env, AskRouting=[routing("none", "again")])
    assert post(env, "again", body["id"]).status_code == 200
    assert "Earlier questions, oldest first:\n(none)" in env["llm"].prompts[-1]


def test_audit_rows(env):  # noqa: F811 - AC-71
    script(env, AskRouting=[routing("benchmark_sectors", "s")])
    post(env, "a")
    post(env, "b")  # nothing scripted left: routing raises
    assert [r["endpoint"] for r in audit(env)] == ["ask.benchmark_sectors", "ask.error"]


def test_tool_failure_is_stored_and_audited_under_the_tool(env, monkeypatch):  # noqa: F811 - AC-71b
    script(env, AskRouting=[routing("transition_plan", company="BASF")])

    def boom(*a, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr(env["run_store"], "list_runs", boom)
    r = post(env, "q71b")
    assert r.status_code == 200 and (r.json()["tool"], r.json()["error"]) == (None, ERROR_DETAIL)
    assert audit(env)[-1]["endpoint"] == "ask.transition_plan"


def test_viewer_reads_but_cannot_ask(env, pg):  # noqa: F811 - AC-71c, AC-71e
    as_viewer()
    assert post(env, "x").status_code == 403
    assert stored(pg) == 0
    assert env["client"].get("/api/agent/ask-threads").status_code == 200


def test_refused_requests_leave_no_audit_row(env):  # noqa: F811 - AC-71f
    script(env, AskRouting=[routing("none")])
    assert post(env, "x", ZERO).status_code == 404
    assert post(env, "   ").status_code == 422
    as_viewer()
    assert post(env, "x").status_code == 403
    app.dependency_overrides[authorize] = app.dependency_overrides[current_user] = lambda: Principal(user_id="u_a", name="A", role="approver")
    assert audit(env) == []


def test_history_text_is_cut_to_1000_characters(env, pg):  # noqa: F811 - AC-71g
    long = "".join(chr(ord("a") + i % 26) for i in range(1200))
    AskStore(pg).add(thread_id=None, question="q", asked_by="dev", tool="none", standalone_question=long)
    t = AskStore(pg).threads()[0]["thread_id"]
    script(env, AskRouting=[routing("none")])
    r = post(env, "follow", t)
    assert r.status_code == 200 and r.json()["error"] is None
    prompt = env["llm"].prompts[-1]
    assert f"- {long[:1000]} [none]" in prompt and long[:1001] not in prompt


def test_threads_list(env):  # noqa: F811 - AC-72b
    script(env, AskRouting=[routing("none", "a"), routing("none", "b"), routing("none", "c")])
    a = post(env, "a" * 70).json()
    post(env, "x", a["id"])
    b = post(env, "b").json()
    rows = env["client"].get("/api/agent/ask-threads").json()
    assert [r["thread_id"] for r in rows] == [b["id"], a["id"]]
    assert {**rows[1], "created_at": None} == {"thread_id": a["id"], "title": "a" * 60, "status": "answered", "created_at": None, "asks": 2}
    assert rows[1]["created_at"].startswith(a["created_at"][:19])


def test_thread_status_follows_its_newest_ask(env):  # noqa: F811
    script(env, AskRouting=[routing("none", "a")])
    t = post(env, "a").json()["id"]
    post(env, "b", t)  # fails
    assert env["client"].get("/api/agent/ask-threads").json()[0]["status"] == "failed"


@pytest.fixture
def planner(pg, env, fake_llm, monkeypatch):  # noqa: F811
    """`POST /api/plans` with a planner that writes one valid script and no saved-universe check."""
    monkeypatch.setattr(plans, "_context", lambda: "")
    monkeypatch.setattr(plans, "_check_sources", lambda steps: [])
    llm = fake_llm({"PlanScript": [PlanScript(script='u = universe_build(taxonomy_id="t", source="u.csv")\n')]})
    monkeypatch.setattr("arp.api.deps.get_llm_client", lambda: llm)
    return env["client"]


def test_plan_from_an_ask(planner, env, pg):  # noqa: F811 - AC-73, AC-73d, AC-73e
    script(env, AskRouting=[routing("none", "s")])
    a = post(env, "sector weights of msci world").json()
    r = planner.post("/api/plans", json={"brief": "b73", "source_ask_id": a["id"]})
    assert r.status_code == 200, r.text
    p = r.json()
    assert (p["source_ask_id"], p["status"]) == (a["id"], "draft")
    assert planner.get(f"/api/plans/{p['id']}").json()["source_ask"] == {"question": "sector weights of msci world", "thread_id": a["id"]}
    [row] = planner.get("/api/agent/asks", params={"thread_id": a["id"]}).json()
    assert row["plans"] == [{"plan_id": p["id"], "brief": "b73", "status": "draft"}]


def test_plan_without_ask_has_null_source(planner, pg):  # AC-73c
    p = planner.post("/api/plans", json={"brief": "b"}).json()
    got = planner.get(f"/api/plans/{p['id']}").json()
    assert (got["source_ask_id"], got["source_ask"]) == (None, None)
    assert planner.get("/api/plans").json()[0]["source_ask"] is None


def test_plan_from_unknown_ask_is_404(planner, pg):  # AC-72e, AC-73b
    for bad in ("abc", ZERO):
        r = planner.post("/api/plans", json={"brief": "b", "source_ask_id": bad})
        assert (r.status_code, r.json()) == (404, {"detail": "ask not found"})
    assert PlanStore(pg).list() == []


def _set_created(pg, ask_id: str, at: str) -> None:
    from sqlalchemy import update

    with Session(get_engine(pg)) as s, s.begin():
        s.execute(update(AgentAsk).where(AgentAsk.id == ask_id).values(created_at=at))


def test_thread_and_threads_follow_created_at_not_insert_order(pg):
    """Rows stored out of time order still come back oldest first in a thread and newest first in the list."""
    store = AskStore(pg)
    a = store.add(thread_id=None, question="a", asked_by="dev", tool="none", standalone_question="a")["id"]
    late = store.add(thread_id=a, question="late", asked_by="dev", tool="none", standalone_question="late")["id"]
    early = store.add(thread_id=a, question="early", asked_by="dev", error="x")["id"]
    b = store.add(thread_id=None, question="b", asked_by="dev", tool="none", standalone_question="b")["id"]
    # Updated newest first, so the table's physical order is the reverse of time order.
    _set_created(pg, late, "2026-01-03T00:00:00+00:00")
    _set_created(pg, early, "2026-01-02T00:00:00+00:00")
    _set_created(pg, a, "2026-01-01T00:00:00+00:00")
    _set_created(pg, b, "2025-12-31T00:00:00+00:00")
    assert [x["question"] for x in store.thread(a)] == ["a", "early", "late"]
    rows = store.threads()
    assert [r["thread_id"] for r in rows] == [a, b]
    assert rows[0]["status"] == "answered"  # the newest ask ("late") answered, though "early" was stored last
