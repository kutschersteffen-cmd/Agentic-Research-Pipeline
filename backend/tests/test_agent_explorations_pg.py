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
    """Answers /execute with `reply(request_json)` and records each such request; answers /check with
    `check(request_json)` and records its code in `checked`."""
    state = {"requests": [], "reply": lambda body: {"status": "done", "result": 1, "error": None},
             "checked": [], "check": lambda body: {"ok": True, "error": None}}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/check":
            state["checked"].append(body["code"])
            return httpx.Response(200, json=state["check"](body))
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


def test_a_busy_sandbox_says_so(client, standins, monkeypatch):
    busy = httpx.MockTransport(lambda request: httpx.Response(429, json={"detail": "sandbox busy: 4 of 4 executions running"}))
    monkeypatch.setattr(sandbox.httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=busy, **kw))
    body = _explore(client, standins, "q5b", "return 1").json()
    assert (body["status"], body["error"]) == (
        "failed", "sandbox at http://sandbox.test is busy (too many code runs at once); try again in a moment")


def test_no_stand_in_code_is_502(client, standins, sandbox_service):
    (standins / "explore.json").write_text("{}")
    res = client.post("/api/agent/explorations", json={"question": "unknown"})
    assert res.status_code == 502
    assert sandbox_service["requests"] == []


# Slice 10: the model call and its retry, list and get, accept, inbox rows.

def _parse_check(body):  # what the sandbox's /check answers for code that does not parse
    if body["code"].rstrip().endswith("("):
        return {"ok": False, "error": "code does not parse: Unexpected token (3:0)"}
    return {"ok": True, "error": None}


def test_code_that_does_not_parse_gets_one_retry(client, standins, sandbox_service):  # AC-45c
    sandbox_service["check"] = _parse_check
    body = _explore(client, standins, "q45c", "return (", "return 1").json()
    assert (body["status"], body["result"], body["code"]) == ("done", 1, "return 1")
    assert sandbox_service["checked"] == ["return (", "return 1"]
    logged = [json.loads(line) for line in (standins / "calls.jsonl").read_text().splitlines()]
    assert logged == [{"kind": "model", "name": "ExplorationCode", "question": "q45c"}] * 2


def test_a_second_parse_failure_is_stored_failed_without_running(client, standins, sandbox_service):
    sandbox_service["check"] = _parse_check
    body = _explore(client, standins, "q-bad", "return (", "return (").json()
    assert (body["status"], body["error"], body["tool_calls"]) == (
        "failed", "code does not parse: Unexpected token (3:0)", [])
    assert sandbox_service["requests"] == []


def test_a_line_limit_breach_is_not_retried(client, standins, sandbox_service):
    sandbox_service["check"] = lambda body: {"ok": False, "error": "code exceeds 400 lines"}
    _explore(client, standins, "q-long", "x", "y")
    assert sandbox_service["checked"] == ["x"]
    assert [sent["code"] for _, sent in sandbox_service["requests"]] == ["x"]  # execute reports the breach itself


def test_real_model_gets_the_declarations_and_the_parse_error(pg, sandbox_service, fake_llm):
    import asyncio

    from arp.agent.explorations import ExplorationCode, explore

    sandbox_service["check"] = _parse_check
    llm = fake_llm({"ExplorationCode": [ExplorationCode(code="return ("), ExplorationCode(code="return 2")]})
    settings = Settings(standins_dir=None, sandbox_url="http://sandbox.test", llm_model="claude-sonnet-5-5")
    principal = Principal(user_id="alice", name="alice", role="analyst")
    row = asyncio.run(explore(ExplorationStore(pg), settings, "weights?", principal, llm=llm))
    assert (row["status"], row["result"], row["model"]) == ("done", 1, "claude-sonnet-5-5")
    assert row["cost_usd"] > 0  # both attempts are priced
    first, second = llm.prompts
    assert "benchmark_sectors(args: { benchmark_id?: string | null })" in first
    assert "universe_build" not in first
    assert first.endswith("Question: weights?")
    assert "return (" in second and "code does not parse: Unexpected token (3:0)" in second


def test_declarations_cover_the_sandbox_lane_only():
    from arp.agent.explorations import declarations
    from arp.orchestration.capabilities import CATALOG

    text = declarations()
    for cap in CATALOG:
        assert (f"  {cap.id}(args:" in text) == (cap.lane == "sandbox")


def test_list_newest_first_and_get(client, standins, sandbox_service):
    a = _explore(client, standins, "qa", "return 1").json()
    b = _explore(client, standins, "qb", "return 1").json()
    assert [e["id"] for e in client.get("/api/agent/explorations").json()] == [b["id"], a["id"]]
    assert client.get(f"/api/agent/explorations/{a['id']}").json() == a
    for missing in ("00000000-0000-0000-0000-000000000000", "abc"):
        res = client.get(f"/api/agent/explorations/{missing}")
        assert (res.status_code, res.json()) == (404, {"detail": "exploration not found"})


def test_accept_labels_it_accepted_by_the_user(client, standins, sandbox_service):  # AC-48
    e = _explore(client, standins, "q48", "return 1").json()
    res = client.post(f"/api/agent/explorations/{e['id']}/accept")
    assert res.status_code == 200
    got = client.get(f"/api/agent/explorations/{e['id']}").json()
    assert (got["label"], got["accepted_by"]) == ("accepted", "alice")
    assert got["accepted_at"] is not None
    client.app.dependency_overrides[current_user] = lambda: Principal(user_id="bob", name="bob", role="analyst")
    again = client.post(f"/api/agent/explorations/{e['id']}/accept").json()
    assert (again["accepted_by"], again["accepted_at"]) == ("alice", got["accepted_at"])  # the first acceptance stays
    res = client.post("/api/agent/explorations/00000000-0000-0000-0000-000000000000/accept")
    assert (res.status_code, res.json()) == (404, {"detail": "exploration not found"})


def test_accept_refuses_a_failed_or_timed_out_exploration(pg, client):
    from arp.agent.explorations import ExplorationStore

    store = ExplorationStore(pg)
    ids = {st: store.add(question=st, code="return 1", model="stand-in", run={
        "status": st, "result": None, "error": "boom", "tool_calls": []})["id"] for st in ("failed", "timeout")}
    for st, eid in ids.items():
        res = client.post(f"/api/agent/explorations/{eid}/accept")
        assert (res.status_code, res.json()) == (409, {"detail": "only a done exploration can be accepted"})
        got = client.get(f"/api/agent/explorations/{eid}").json()
        assert (got["accepted_at"], got["label"], got["status"]) == (None, "exploratory", st)


def test_inbox_lists_explorations_not_yet_accepted(pg, client, standins, sandbox_service):  # AC-50
    from arp.api.deps import get_run_store
    from arp.api.routers import plans
    from arp.orchestration.plan_store import PlanStore

    client.app.dependency_overrides[plans.plan_store] = lambda: PlanStore(pg)
    client.app.dependency_overrides[get_run_store] = lambda: None
    waiting = _explore(client, standins, "q50 " + "x" * 80, "return 1").json()
    done = _explore(client, standins, "q50b", "return 1").json()
    client.post(f"/api/agent/explorations/{done['id']}/accept")
    rows = client.get("/api/agent/inbox").json()
    assert rows == [{"kind": "exploration", "plan_id": None, "seq": None, "exploration_id": waiting["id"],
                     "title": waiting["question"][:60], "href": f"#/agent/exploration/{waiting['id']}"}]


def test_golden_case_passes_on_done_with_every_expected_capability(monkeypatch):  # AC-51's pass rule
    import asyncio

    from arp.agent import golden

    def runs(status, called, error=None):
        async def fake(settings, question, principal, llm=None):
            return "code", "m", 0.0, {"status": status, "result": None, "error": error,
                                      "tool_calls": [{"capability_id": c, "args": {}, "result_bytes": 1} for c in called]}
        return fake

    case = {"id": "x", "question": "q", "expected_capabilities": ["benchmark_sectors", "transition_plan"]}
    for fake, why in [(runs("done", ["transition_plan", "benchmark_sectors"]), None),
                      (runs("done", ["benchmark_sectors"]), "did not call transition_plan"),
                      (runs("failed", [], "boom"), "failed: boom")]:
        monkeypatch.setattr(golden, "run_question", fake)
        assert asyncio.run(golden.run_case(None, None, case)) == why


ZERO = "00000000-0000-0000-0000-000000000000"


def _ask(pg, question="Sector weights?") -> dict:
    from arp.orchestration.ask_store import AskStore

    return AskStore(pg).add(thread_id=None, question=question, asked_by="alice", tool="benchmark_sectors",
                            standalone_question=question)


def test_exploration_from_an_ask_links_both_ways(pg, client, standins, sandbox_service):  # AC-80 (unit side)
    from arp.orchestration.ask_store import AskStore

    client.app.dependency_overrides[agent.ask_store] = lambda: AskStore(pg)
    a = _ask(pg, "Sector weights of MSCI World?")
    (standins / "explore.json").write_text(json.dumps({"q80": [{"code": "return 1"}]}))
    res = client.post("/api/agent/explorations", json={"question": "q80", "source_ask_id": a["id"]})
    assert res.status_code == 200, res.text
    e = res.json()
    source = {"question": "Sector weights of MSCI World?", "thread_id": a["id"]}
    assert (e["source_ask_id"], e["source_ask"]) == (a["id"], source)
    assert client.get(f"/api/agent/explorations/{e['id']}").json()["source_ask"] == source
    assert client.get("/api/agent/explorations").json()[0]["source_ask"] == source
    [row] = client.get("/api/agent/asks", params={"thread_id": a["id"]}).json()
    assert row["explorations"] == [{"exploration_id": e["id"], "question": "q80", "status": "done",
                                    "label": "exploratory"}]
    client.post(f"/api/agent/explorations/{e['id']}/accept")
    [row] = client.get("/api/agent/asks", params={"thread_id": a["id"]}).json()
    assert row["explorations"][0]["label"] == "accepted"


def test_exploration_without_ask_has_null_source(client, standins, sandbox_service):
    e = _explore(client, standins, "q", "return 1").json()
    assert (e["source_ask_id"], e["source_ask"]) == (None, None)


def test_exploration_from_unknown_ask_is_404(pg, client, standins, sandbox_service):  # AC-80b (unit side)
    (standins / "explore.json").write_text(json.dumps({"q": [{"code": "return 1"}]}))
    for bad in ("abc", ZERO):
        res = client.post("/api/agent/explorations", json={"question": "q", "source_ask_id": bad})
        assert (res.status_code, res.json()) == (404, {"detail": "ask not found"})
    assert client.get("/api/agent/explorations").json() == []
    assert sandbox_service["requests"] == []
