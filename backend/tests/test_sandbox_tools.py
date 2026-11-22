"""The sandbox's tool route and execution tokens (spec agent-panel-code-mode, AC-46, AC-47 and limits)."""
from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.agent import sandbox
from arp.api.auth import Principal
from arp.api.routers import sandbox_tools
from arp.config import Settings

ALICE = Principal(user_id="alice", name="alice", role="analyst")


@pytest.fixture
def client(monkeypatch):
    async def fake_call(capability_id, args, principal):
        return {"capability": capability_id, "args": args.model_dump(), "user": principal.user_id}

    monkeypatch.setattr(sandbox, "call_capability", fake_call)
    app = FastAPI()
    app.include_router(sandbox_tools.router)
    return TestClient(app)


def _token(seconds: float = 60) -> str:
    return sandbox.mint_token(sorted(sandbox.SANDBOX_CAPABILITIES), ALICE, Settings(sandbox_token_seconds=seconds))


def _post(client, capability_id, token, body=None):
    return client.post(f"/api/sandbox/tools/{capability_id}", json=body or {}, headers={"Authorization": f"Bearer {token}"})


def test_plan_lane_capability_has_no_route(client):  # AC-46
    assert _post(client, "universe_build", _token()).status_code == 404


def test_expired_token_is_refused(client):  # AC-47
    token = _token(seconds=1)
    time.sleep(2)
    assert _post(client, "smart_search", token, {"question": "q"}).status_code == 401


def test_missing_unknown_and_released_tokens_are_refused(client):
    assert client.post("/api/sandbox/tools/smart_search", json={"question": "q"}).status_code == 401
    assert _post(client, "smart_search", "nope", {"question": "q"}).status_code == 401
    token = _token()
    sandbox.release(token)
    assert _post(client, "smart_search", token, {"question": "q"}).status_code == 401


def test_call_runs_as_the_minting_user_and_is_logged(client):
    token = _token()
    res = _post(client, "benchmark_sectors", token, {"benchmark_id": None})
    assert res.status_code == 200
    assert res.json() == {"capability": "benchmark_sectors", "args": {"benchmark_id": None}, "user": "alice"}
    assert sandbox.release(token).tool_calls == [
        {"capability_id": "benchmark_sectors", "args": {"benchmark_id": None}, "result_bytes": len(res.content)}]


def test_token_only_covers_its_capabilities(client):
    token = sandbox.mint_token(["benchmark_sectors"], ALICE)
    assert _post(client, "smart_search", token, {"question": "q"}).status_code == 403


def test_bad_arguments_answer_422(client):
    res = _post(client, "benchmark_sectors", _token(), {"benchmark": "x"})
    assert res.status_code == 422
    assert res.json()["detail"].startswith("benchmark_sectors: benchmark: ")


def test_fifty_calls_then_the_limit(client):
    token = _token()
    for _ in range(50):
        assert _post(client, "benchmark_sectors", token).status_code == 200
    res = _post(client, "benchmark_sectors", token)
    assert (res.status_code, res.json()["detail"]) == (429, "capability call limit 50 exceeded")
    execution = sandbox.release(token)
    assert len(execution.tool_calls) == 50
    assert execution.breach == "capability call limit 50 exceeded"
