"""Write action: an accepted exploration becomes a draft plan (spec agent-panel-code-mode, Phase 6, slice 12)."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from arp.agent.explorations import ExplorationStore, plan_context
from arp.agent.models import AgentExploration
from arp.api.routers import agent, plans
from arp.config import get_settings
from arp.orchestration.plan_planner import PlanRejected, PlanScript
from arp.orchestration.plan_store import PlanStore, _checked_dry_run
from arp.orchestration.plan_worker import scan
from arp.storage.postgres import get_engine
from tests.test_plan_worker_pg import P3, P3Stubs

ZERO = "00000000-0000-0000-0000-000000000000"
SCRIPT = 'u = universe_build(taxonomy_id="t", source="u.csv")\n'
TAIL = "\n(result truncated at 20000 bytes)"


def _exploration(pg, question="q", result=None, status="done", accepted=True) -> str:
    store = ExplorationStore(pg)
    row = store.add(question=question, code="return 1", model="stand-in",
                    run={"status": status, "result": result, "error": None, "tool_calls": []})
    if accepted:
        store.accept(row["id"], "alice")
    return row["id"]


@pytest.fixture
def env(pg, fake_llm, monkeypatch):
    """The agent and plans routers with a planner that writes `SCRIPT` and no saved-universe check."""
    monkeypatch.setattr(plans, "_context", lambda: "CTX")
    monkeypatch.setattr(plans, "_check_sources", lambda steps: [])
    llm = fake_llm({"PlanScript": [PlanScript(script=SCRIPT)]})
    monkeypatch.setattr("arp.api.deps.get_llm_client", lambda: llm)
    app = FastAPI()
    app.include_router(agent.router)
    app.include_router(plans.router)
    app.dependency_overrides[agent.exploration_store] = lambda: ExplorationStore(pg)
    return {"client": TestClient(app), "llm": llm, "pg": pg}


@pytest.fixture
def contexts(monkeypatch):
    """An injected planner: records the `context` the route passes to `draft_plan`, then rejects the draft."""
    seen: list[str] = []

    async def planner(brief, llm, store, context="", check=None, source_exploration_id=None, **_):
        seen.append(context)
        raise PlanRejected("stop")

    monkeypatch.setattr(agent, "draft_plan", planner)
    return seen


def test_accepted_exploration_drafts_a_linked_plan(env):  # AC-60 (unit side)
    e = _exploration(env["pg"], "Q60")
    r = env["client"].post(f"/api/agent/explorations/{e}/plan", json={"brief": "fetch missing reports"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert (p["status"], p["approved_by"], p["brief"], p["source_exploration_id"]) == ("draft", None, "fetch missing reports", e)
    assert p["source_exploration"] == {"question": "Q60"}
    assert {"calls", "spent_usd"} <= p.keys()  # as GET /api/plans/{id} answers
    got = env["client"].get(f"/api/plans/{p['id']}").json()
    assert got["source_exploration_id"] == e
    assert env["client"].get("/api/plans").json()[0]["source_exploration_id"] == e


def test_plan_drafted_elsewhere_has_null_source(env):  # AC-60b (unit side)
    p = env["client"].post("/api/plans", json={"brief": "b"}).json()
    got = env["client"].get(f"/api/plans/{p['id']}").json()
    assert (got["source_exploration_id"], got["source_exploration"]) == (None, None)
    assert {"id", "brief", "script", "status", "source_ask_id", "source_ask", "calls", "spent_usd"} <= got.keys()


def test_not_accepted_is_409_and_stores_no_plan(env):  # AC-61 (unit side)
    e = _exploration(env["pg"], accepted=False)
    r = env["client"].post(f"/api/agent/explorations/{e}/plan", json={"brief": "x"})
    assert (r.status_code, r.json()) == (409, {"detail": "only an accepted exploration can become a plan"})
    assert PlanStore(env["pg"]).list() == []
    assert env["llm"].calls == []


@pytest.mark.parametrize("bad", [ZERO, "not-a-uuid"])
def test_unknown_exploration_is_404(env, bad):  # AC-61b (unit side)
    r = env["client"].post(f"/api/agent/explorations/{bad}/plan", json={"brief": "x"})
    assert (r.status_code, r.json()) == (404, {"detail": "exploration not found"})


def test_failed_but_accepted_is_409(env):  # AC-61c
    e = _exploration(env["pg"], accepted=False)
    with Session(get_engine(env["pg"])) as s, s.begin():
        s.execute(update(AgentExploration).where(AgentExploration.id == uuid.UUID(e))
                  .values(status="failed", accepted_at=datetime.now(UTC), accepted_by="alice"))
    r = env["client"].post(f"/api/agent/explorations/{e}/plan", json={"brief": "x"})
    assert (r.status_code, r.json()) == (409, {"detail": "only an accepted exploration can become a plan"})
    assert PlanStore(env["pg"]).list() == []


@pytest.mark.parametrize("body", [{"brief": "   "}, {"brief": None}, {}, None])
def test_blank_or_missing_brief_is_the_question(env, body):  # AC-62 (unit side)
    e = _exploration(env["pg"], "Q62")
    r = env["client"].post(f"/api/agent/explorations/{e}/plan", **({} if body is None else {"json": body}))
    assert r.status_code == 200, r.text
    assert r.json()["brief"] == "Q62"


def test_prompt_carries_the_exploration(env):  # AC-62b (unit side)
    e = _exploration(env["pg"], "Q62b", result=[{"a": 1}])
    assert env["client"].post(f"/api/agent/explorations/{e}/plan", json={}).status_code == 200
    [prompt] = env["llm"].prompts
    assert f"\nCTX\n\nFrom exploration {e}, question: Q62b\nResult:\n[{{\"a\":1}}]" in prompt


def test_long_result_is_cut_at_20000_bytes(env, contexts):  # AC-63
    result = "a" * 29_998
    e = _exploration(env["pg"], result=result)
    assert env["client"].post(f"/api/agent/explorations/{e}/plan", json={}).status_code == 422
    [context] = contexts
    whole = json.dumps(result)
    assert len(whole.encode()) == 30_000
    assert context.startswith("CTX\n\n")
    assert context.endswith("Result:\n" + whole[:20_000] + TAIL)


def test_cut_never_splits_a_character(env, contexts):  # AC-63b
    result = "a" * 19_997 + "€" + "b" * 100  # JSON: the quote, then bytes 2..19998 "a", "€" at bytes 19999..20001
    assert json.dumps(result, ensure_ascii=False).encode()[19_998:20_001] == "€".encode()
    e = _exploration(env["pg"], result=result)
    env["client"].post(f"/api/agent/explorations/{e}/plan", json={})
    [context] = contexts
    assert context.endswith(TAIL)
    text = context.split("Result:\n", 1)[1][: -len(TAIL)]
    assert len(text.encode()) == 19_998
    assert text.encode().decode() == text


def test_result_of_exactly_20000_bytes_is_whole(env, contexts):  # AC-63c
    result = "a" * 19_998
    whole = json.dumps(result)
    assert len(whole.encode()) == 20_000
    e = _exploration(env["pg"], result=result)
    env["client"].post(f"/api/agent/explorations/{e}/plan", json={})
    [context] = contexts
    assert context.endswith("Result:\n" + whole)
    assert "result truncated" not in context


def test_plan_context_shape():
    assert plan_context({"id": "E", "question": "Q", "result": {"k": "ü"}}) == 'From exploration E, question: Q\nResult:\n{"k":"ü"}'


def test_rejected_twice_is_422_and_stores_nothing(env, fake_llm, monkeypatch):  # AC-63d
    bad = PlanScript(script="x = exploration\n")
    llm = fake_llm({"PlanScript": [bad, bad]})
    monkeypatch.setattr("arp.api.deps.get_llm_client", lambda: llm)
    e = _exploration(env["pg"])
    r = env["client"].post(f"/api/agent/explorations/{e}/plan", json={"brief": "x"})
    assert r.status_code == 422
    with pytest.raises(ValueError) as checker:
        _checked_dry_run("x = exploration\n")
    assert r.json() == {"detail": str(checker.value)}
    assert llm.calls == ["PlanScript", "PlanScript"]
    assert [p for p in PlanStore(env["pg"]).list() if p["source_exploration_id"] == e] == []


def test_worker_skips_a_draft_from_an_exploration(pg, monkeypatch):  # AC-64
    monkeypatch.setenv("ARP_PLAN_WORKER_SECONDS", "0")
    get_settings.cache_clear()
    store = PlanStore(pg)
    plan_id = store.create("b", P3, source_exploration_id=_exploration(pg))
    stubs = P3Stubs()
    assert scan(store, stubs.steps(), lambda c: True) == []
    assert scan(store, stubs.steps(), lambda c: True) == []
    assert store.get(plan_id)["status"] == "draft"
    assert store.calls(plan_id) == []
    assert not stubs.starts
    keys = [json.loads(m.read_text()).get("params", {}).get("launch_key") or ""
            for m in get_settings().runs_dir.glob("**/manifest.json")]
    assert not [k for k in keys if k.startswith(f"plan:{plan_id}:")]
