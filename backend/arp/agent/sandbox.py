"""The backend's side of the sandbox lane (spec agent-panel-code-mode, Phase 4): per-execution tool tokens, the
sandbox lane's read capabilities as the tool route calls them, and the client for the `sandbox/` service.

A token is a random string the backend keeps in memory with its capability list, expiry and call log; it is sent to
the sandbox's host worker only, never into the isolate. Tokens live in this process, so they need the single API
process ARP runs today; another process answers 401.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel

from arp.api.auth import Principal
from arp.config import Settings, get_settings
from arp.orchestration.capabilities import CATALOG

SANDBOX_CAPABILITIES = {c.id: c for c in CATALOG if c.lane == "sandbox"}
CALL_LIMIT = 50
CALL_LIMIT_ERROR = f"capability call limit {CALL_LIMIT} exceeded"
SANDBOX_TIMEOUT_SECONDS = 45  # above the sandbox's 30 s wall time, which answers `timeout` itself


@dataclass
class Execution:
    capabilities: frozenset[str]
    expires: float  # time.monotonic()
    principal: Principal
    tool_calls: list[dict] = field(default_factory=list)  # [{capability_id, args, result_bytes}]
    breach: str | None = None


_EXECUTIONS: dict[str, Execution] = {}  # sha256 of the token -> its execution
_LOCK = threading.Lock()


def _key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def mint_token(capabilities: list[str], principal: Principal, settings: Settings | None = None) -> str:
    seconds = (settings or get_settings()).sandbox_token_seconds
    token = secrets.token_urlsafe(32)
    with _LOCK:
        now = time.monotonic()
        for key in [k for k, e in _EXECUTIONS.items() if e.expires < now]:
            del _EXECUTIONS[key]
        _EXECUTIONS[_key(token)] = Execution(frozenset(capabilities), now + seconds, principal)
    return token


def execution_for(token: str) -> Execution | None:
    """The token's execution, or None when it is unknown, expired or released."""
    with _LOCK:
        execution = _EXECUTIONS.get(_key(token))
    return execution if execution and execution.expires >= time.monotonic() else None


def release(token: str) -> Execution | None:
    with _LOCK:
        return _EXECUTIONS.pop(_key(token), None)


def reserve_call(execution: Execution, capability_id: str, args: Any) -> dict | None:
    """The call's log row, or None once the execution has made CALL_LIMIT calls (which marks the breach)."""
    with _LOCK:
        if len(execution.tool_calls) >= CALL_LIMIT:
            execution.breach = execution.breach or CALL_LIMIT_ERROR
            return None
        row = {"capability_id": capability_id, "args": args, "result_bytes": 0}
        execution.tool_calls.append(row)
        return row


async def call_capability(capability_id: str, args: BaseModel, principal: Principal) -> Any:
    """Runs one sandbox-lane read capability, as Ask ARP's tools run, and returns its JSON value."""
    from starlette.concurrency import run_in_threadpool

    from arp import ask
    from arp.api import deps

    if capability_id == "benchmark_sectors":
        card, _text = await run_in_threadpool(ask.benchmark_sectors, deps.get_stream_store().root, args.benchmark_id)
        return card.model_dump(mode="json") if card else None
    if capability_id == "transition_plan":
        card, _text = await run_in_threadpool(ask.newest_transition_plan, deps.get_run_store(), principal, args.company)
        return card.model_dump(mode="json") if card else None
    if capability_id == "portfolio_exposure":
        from arp.portfolio import qa_agent
        from arp.storage.portfolio_store import portfolio_directories

        store = deps.get_portfolio_store()
        securities, companies = await run_in_threadpool(portfolio_directories, store)
        answer, _usage = await qa_agent.answer_question(args.question, deps.get_llm_client(), store, securities, companies)
        return answer.model_dump(mode="json")
    if capability_id == "smart_search":
        from datetime import date

        from arp import smart_search
        from arp.api.routers.security_master import datahub_lists

        settings = get_settings()
        lists = await run_in_threadpool(
            datahub_lists, settings, deps.get_portfolio_store(), deps.get_identifier_map(settings), deps.get_run_store(),
            deps.get_decision_store(), deps.get_taxonomy_store(), deps.get_index_store(), deps.get_reporting_store(),
            date.today())
        found, _usage = await smart_search.smart_search(args.question, deps.get_llm_client(), **lists)
        return found.model_dump(mode="json")
    raise LookupError(capability_id)


async def execute(code: str, principal: Principal, settings: Settings | None = None) -> dict[str, Any]:
    """Runs `code` in the sandbox with a fresh token for the sandbox lane. Returns {status, result, error, tool_calls}."""
    settings = settings or get_settings()
    token = mint_token(sorted(SANDBOX_CAPABILITIES), principal, settings)
    try:
        async with httpx.AsyncClient(timeout=SANDBOX_TIMEOUT_SECONDS) as client:
            res = await client.post(f"{settings.sandbox_url.rstrip('/')}/execute",
                                    json={"code": code, "token": token, "capabilities": sorted(SANDBOX_CAPABILITIES)})
        res.raise_for_status()
        out = res.json()
        status, result, error = out["status"], out.get("result"), out.get("error")
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        status, result, error = "failed", None, f"sandbox at {settings.sandbox_url} did not answer: {type(exc).__name__}"
    execution = release(token)
    calls = execution.tool_calls if execution else []
    if execution and execution.breach and status != "timeout":
        status, result, error = "failed", None, execution.breach
    if status != "done":
        result = None
    return {"status": status, "result": result, "error": error, "tool_calls": calls}


def result_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))  # as JSONResponse sends it
