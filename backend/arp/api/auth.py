from __future__ import annotations

import json
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError

from arp.api.deps import settings_dep
from arp.config import Settings

ROLE_RANK: dict[str, int] = {"viewer": 0, "analyst": 1, "approver": 2}
LOOPBACK_HOSTS = {"127.0.0.1", "::1"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class Principal(BaseModel):
    user_id: str
    name: str
    role: Literal["viewer", "analyst", "approver"]


class _UserRow(Principal):
    token: str


@lru_cache
def load_users(path: Path) -> dict[str, Principal]:
    """token -> Principal. Raises RuntimeError naming the path when the file is missing or invalid."""
    try:
        rows = json.loads(Path(path).read_text(encoding="utf-8"))["users"]
        users = [_UserRow.model_validate(r) for r in rows]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Never put str(exc) here: a pydantic ValidationError echoes the offending row, token included.
        if isinstance(exc, ValidationError):
            why = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['type']}" for e in exc.errors(include_input=False))
        else:
            why = type(exc).__name__
        raise RuntimeError(f"Users file {path} is missing or invalid ({why}); see config/users.example.json.") from None
    return {u.token: Principal(user_id=u.user_id, name=u.name, role=u.role) for u in users}


async def current_user(request: Request, settings: Settings = Depends(settings_dep)) -> Principal:
    if settings.auth_mode == "dev" and request.client and request.client.host in LOOPBACK_HOSTS:
        return Principal(user_id=settings.dev_user, name=settings.dev_user, role="approver")
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    user = load_users(settings.users_file).get(token.strip()) if scheme.lower() == "bearer" else None
    if user is None:
        raise HTTPException(401, "Missing or invalid bearer token", headers={"WWW-Authenticate": "Bearer"})
    return user


def require_role(min_role: str) -> Callable:
    async def dependency(user: Principal = Depends(current_user)) -> Principal:
        if ROLE_RANK[user.role] < ROLE_RANK[min_role]:
            raise HTTPException(403, f"Requires role '{min_role}' or higher")
        return user

    return dependency


_viewer, _analyst = require_role("viewer"), require_role("analyst")


async def authorize(request: Request, user: Principal = Depends(current_user)) -> Principal:
    """Router-level dependency: viewer may read, analyst may change anything."""
    return await (_viewer if request.method in SAFE_METHODS else _analyst)(user)
