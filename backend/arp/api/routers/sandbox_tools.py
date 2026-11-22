"""The sandbox's tool route (spec agent-panel-code-mode, Phase 4): the sandbox's host worker calls a read capability
here with its execution's token. Only sandbox-lane capabilities have a route; the token, not a user session, signs the
call in, so this router is mounted without the app's `authorize` dependency."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from arp.agent import sandbox

router = APIRouter(prefix="/api/sandbox/tools", tags=["sandbox"])


@router.post("/{capability_id}", include_in_schema=False)
async def call_tool(capability_id: str, request: Request) -> Any:
    capability = sandbox.SANDBOX_CAPABILITIES.get(capability_id)
    if capability is None:
        raise HTTPException(404, "Not Found")
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    execution = sandbox.execution_for(token.strip()) if scheme.lower() == "bearer" and token.strip() else None
    if execution is None:
        raise HTTPException(401, "Missing, invalid or expired execution token", headers={"WWW-Authenticate": "Bearer"})
    if capability_id not in execution.capabilities:
        raise HTTPException(403, f"{capability_id} is not granted to this execution")
    try:
        raw = await request.json()
    except ValueError:
        raw = None
    row = sandbox.reserve_call(execution, capability_id, raw)
    if row is None:
        raise HTTPException(429, sandbox.CALL_LIMIT_ERROR)
    try:
        args = capability.input_model.model_validate(raw if raw is not None else {})
    except ValidationError as exc:
        first = exc.errors(include_input=False)[0]
        where = ".".join(str(p) for p in first["loc"]) or "(arguments)"
        raise HTTPException(422, f"{capability_id}: {where}: {first['msg']}") from None
    try:
        result = await sandbox.call_capability(capability_id, args, execution.principal)
    except Exception as exc:  # noqa: BLE001 - the code sees why its call failed, never a stack trace
        raise HTTPException(502, f"{capability_id} failed: {type(exc).__name__}") from exc
    row["result_bytes"] = sandbox.result_bytes(result)
    return JSONResponse(result)
