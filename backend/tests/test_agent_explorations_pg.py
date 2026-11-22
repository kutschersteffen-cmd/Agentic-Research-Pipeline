"""POST /api/agent/explorations with stand-in code and a stand-in sandbox service (spec agent-panel-code-mode, slice 9).
The sandbox's own behaviour (no network, limits, timeouts) is tested in sandbox/test/."""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.agent import sandbox
from arp.agent.explorations import ExplorationStore
from arp.api.auth import Principal, current_user
from arp.api.deps import settings_dep
from arp.api.routers import agent
from arp.config import Settings

REAL_CLIENT = httpx.AsyncClient


@pytest.fixture
def standins(tmp_path):
    folder = tmp_path / "standins"
    folder.mkdir()
    return folder


@pytest.fixture
def sandbox_service(monkeypatch):
    """Answers /execute with `reply(request_json)`; records each request."""
    state = {"requests": [], "reply": lambda body: {"status": "done", "result": 1, "error": None}}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        state["requests"].append((str(request.url), body))
        return httpx.Response(200, json=state["reply"](body))

    monkeypatch.setattr(sandbox.httpx, "AsyncClient",
                        lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))
    return state


@pytest.fixture
def client(pg, standins):
    settings = Settings(standins_dir=standins, anthropic_api_key=None, gemini_api_key=None,
                        sandbox_url="http://sandbox.test")
    app = FastAPI()
    app.include_router(agent.router)
    app.dependency_overrides[agent.exploration_store] = lambda: ExplorationStore(pg)
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[current_user] = lambda: Principal(user_id="alice", name="alice", role="analyst")
    return TestClient(app)


def _explore(client, standins, question, *codes):
    (standins / "explore.json").write_text(json.dumps({question: [{"code": c} for c in codes]}))
    return client.post("/api/agent/explorations", json={"question": question})


def test_runs_entry_one_and_stores_the_row(pg, client, standins, sandbox_service):
    res = _explore(client, standins, "q1", "return 1", "return 2")
    assert res.status_code == 200
    body = res.json()
    assert {k: body[k] for k in ("question", "code", "status", "result", "error", "tool_calls", "model", "label",
                                 "accepted_by", "accepted_at", "cost_usd")} == {
        "question": "q1", "code": "return 1", "status": "done", "result": 1, "error": None, "tool_calls": [],
        "model": "stand-in", "label": "exploratory", "accepted_by": None, "accepted_at": None, "cost_usd": 0.0}
    [(url, sent)] = sandbox_service["requests"]
    assert url == "http://sandbox.test/execute"
    assert sent["code"] == "return 1"
    assert sent["capabilities"] == sorted(sandbox.SANDBOX_CAPABILITIES)
    assert sandbox.execution_for(sent["token"]) is None  # released once the execution ends
    logged = [json.loads(line) for line in (standins / "calls.jsonl").read_text().splitlines()]
    assert logged == [{"kind": "model", "name": "ExplorationCode", "question": "q1"}]
    with ExplorationStore(pg).engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT id::text, status FROM agent_explorations").all() == [(body["id"], "done")]


def test_failed_and_timeout_answer_200_with_the_row(client, standins, sandbox_service):
    sandbox_service["reply"] = lambda body: {"status": "failed", "result": None, "error": "network access is not allowed"}
    body = _explore(client, standins, "q2", 'return await fetch("https://example.com")').json()
    assert (body["status"], body["result"], body["error"]) == ("failed", None, "network access is not allowed")
    sandbox_service["reply"] = lambda body: {"status": "timeout", "result": None, "error": "execution exceeded 30 s"}
    assert _explore(client, standins, "q3", "while (true) {}").json()["status"] == "timeout"


def test_tool_calls_and_the_limit_come_from_the_tool_route(client, standins, sandbox_service):
    def reply(body):  # the host worker spends the token as the code calls capabilities
        execution = sandbox.execution_for(body["token"])
        for _ in range(51):
            sandbox.reserve_call(execution, "benchmark_sectors", {"benchmark_id": None})
        return {"status": "done", "result": "caught it", "error": None}

    sandbox_service["reply"] = reply
    body = _explore(client, standins, "q4", "loop").json()
    assert (body["status"], body["result"], body["error"]) == ("failed", None, "capability call limit 50 exceeded")
    assert len(body["tool_calls"]) == 50
    assert body["tool_calls"][0] == {"capability_id": "benchmark_sectors", "args": {"benchmark_id": None}, "result_bytes": 0}


def test_sandbox_down_is_a_failed_exploration(client, standins, monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    monkeypatch.setattr(sandbox.httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(refuse), **kw))
    body = _explore(client, standins, "q5", "return 1").json()
    assert (body["status"], body["error"]) == ("failed", "sandbox at http://sandbox.test did not answer: ConnectError")


def test_no_stand_in_code_is_502(client, standins, sandbox_service):
    (standins / "explore.json").write_text("{}")
    res = client.post("/api/agent/explorations", json={"question": "unknown"})
    assert res.status_code == 502
    assert sandbox_service["requests"] == []
