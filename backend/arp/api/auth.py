from __future__ import annotations

import ipaddress
import json
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

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
    token: str = Field(min_length=1)


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
    tokens, ids = [u.token.strip() for u in users], [u.user_id for u in users]
    if not all(tokens) or len(set(tokens)) != len(tokens) or len(set(ids)) != len(ids):
        # No token text in the message: it ends up in logs.
        raise RuntimeError(f"Users file {path} has a blank or duplicate token or a duplicate user_id.")
    return {u.token.strip(): Principal(user_id=u.user_id, name=u.name, role=u.role) for u in users}


def _dev_trusted(host: str, settings: Settings) -> bool:
    """Loopback, or an address in dev_trusted_networks (the Docker bridge, say)."""
    if host in LOOPBACK_HOSTS:
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in settings.dev_trusted_networks)


async def current_user(request: Request, settings: Settings = Depends(settings_dep)) -> Principal:
    if settings.auth_mode == "dev" and request.client and _dev_trusted(request.client.host, settings):
        return Principal(user_id=settings.dev_user, name=settings.dev_user, role="approver")
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    token = token.strip()
    user = load_users(settings.users_file).get(token) if scheme.lower() == "bearer" and token else None
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
