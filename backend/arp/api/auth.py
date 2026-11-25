from __future__ import annotations

import ipaddress
import json
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Literal, get_args

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from arp.api.deps import settings_dep
from arp.config import Settings
from arp.errors import NotConfigured

ROLE_RANK: dict[str, int] = {"viewer": 0, "analyst": 1, "approver": 2}
LOOPBACK_HOSTS = {"127.0.0.1", "::1"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
Grant = Literal["snapshot_reader", "holdings_reader"]
GRANTS: tuple[str, ...] = get_args(Grant)
logger = logging.getLogger(__name__)


class Principal(BaseModel):
    user_id: str
    name: str
    role: Literal["viewer", "analyst", "approver"]
    roles: list[Grant] = Field(default_factory=list)  # grants beyond the role rank; a typo fails at load


class _UserRow(Principal):
    token: str = Field(min_length=1)


_users_lock = threading.Lock()
_last_good: dict[Path, tuple[tuple[int, int] | None, dict[str, Principal]]] = {}  # path -> (version, users) of the last valid read
_logged: set[tuple[Path, tuple[int, int] | None]] = set()  # (path, version) whose failure was already logged


def load_users(path: Path) -> dict[str, Principal]:
    """token -> Principal, re-read when the file's (mtime, size) changes. A broken or missing file keeps the users
    of the last valid read (logged once per version); with none, raises RuntimeError naming the path."""
    try:
        st = Path(path).stat()
        version: tuple[int, int] | None = (st.st_mtime_ns, st.st_size)
    except OSError:
        version = None
    with _users_lock:
        last = _last_good.get(path)
        if last is not None and last[0] == version:
            return last[1]
        try:
            users = _read_users(path)
        except NotConfigured as exc:
            if last is None:
                raise
            if (path, version) not in _logged:
                _logged.add((path, version))
                logger.error("%s Still using the users from the last valid version.", exc)
            return last[1]
        _last_good[path] = (version, users)
        return users


load_users.cache_clear = lambda: (_last_good.clear(), _logged.clear())  # tests: forget every remembered version


def _read_users(path: Path) -> dict[str, Principal]:
    try:
        rows = json.loads(Path(path).read_text(encoding="utf-8"))["users"]
        users = [_UserRow.model_validate(r) for r in rows]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Never put str(exc) here: a pydantic ValidationError echoes the offending row, token included.
        if isinstance(exc, ValidationError):
            why = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['type']}" for e in exc.errors(include_input=False))
        else:
            why = type(exc).__name__
        raise NotConfigured(f"Users file {path} is missing or invalid ({why}); see config/users.example.json.") from None
    tokens, ids = [u.token.strip() for u in users], [u.user_id for u in users]
    if not all(tokens) or len(set(tokens)) != len(tokens) or len(set(ids)) != len(ids):
        # No token text in the message: it ends up in logs.
        raise NotConfigured(f"Users file {path} has a blank or duplicate token or a duplicate user_id.")
    if any(i.strip().lower() == "model" for i in ids):  # four-eyes compares ids case- and space-insensitively
        raise NotConfigured(f"Users file {path}: user id 'model' is reserved.")
    return {u.token.strip(): Principal(**u.model_dump(exclude={"token"})) for u in users}


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
    origin = request.headers.get("Origin")
    # A browser on a foreign site can still send simple cross-origin requests
    # (no preflight) to loopback; those carry its Origin, so no bypass for them.
    # "*" in allowed_origins means any origin, as it does for CORS: behind a reverse proxy the Origin is the proxy's.
    same_site = origin is None or origin in settings.allowed_origins or "*" in settings.allowed_origins
    if settings.auth_mode == "dev" and same_site and request.client and _dev_trusted(request.client.host, settings):
        return Principal(user_id=settings.dev_user, name=settings.dev_user, role="approver", roles=list(GRANTS))
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


def require_grant(*names: str) -> Callable:
    async def dependency(user: Principal = Depends(current_user)) -> Principal:
        for name in names:
            if name not in user.roles:
                raise HTTPException(403, f"Requires role '{name}'")
        return user

    return dependency


_viewer, _analyst = require_role("viewer"), require_role("analyst")


async def authorize(request: Request, user: Principal = Depends(current_user)) -> Principal:
    """Router-level dependency: viewer may read, analyst may change anything."""
    return await (_viewer if request.method in SAFE_METHODS else _analyst)(user)
