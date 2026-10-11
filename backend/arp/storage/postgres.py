from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy import Engine


class PostgresExtraNotInstalled(RuntimeError):
    def __init__(self, exc: Exception) -> None:
        super().__init__(
            "sqlalchemy/psycopg/pgvector aren't installed; they are required dependencies: "
            f"pip install -e . Original import error: {exc}"
        )


# Seconds to wait for a TCP connection to Postgres before giving up.
# Without this, psycopg waits on the OS default, so an unreachable host (a
# firewall dropping packets rather than refusing) stalls every request --
# including engagement_store.py's best-effort mirror on each save -- for
# minutes instead of failing fast.
# pool_pre_ping catches a *stale* pooled connection; it does nothing for a
# server that never answers.
_CONNECT_TIMEOUT_SECONDS = 10


@lru_cache
def get_engine(dsn: str) -> Engine:
    """One pooled Engine per DSN for the process lifetime -- SQLAlchemy's
    own recommended pattern (an Engine already owns a connection pool;
    building a new one per call would defeat that). Imports SQLAlchemy
    lazily so the rest of this codebase never pays an import cost, let
    alone a hard dependency, for a store nobody has opted into.

    A `connect_timeout` already present in the DSN wins -- the caller was
    explicit.
    """
    try:
        from sqlalchemy import create_engine
    except ImportError as exc:  # pragma: no cover - exercised only without the optional extra
        raise PostgresExtraNotInstalled(exc) from exc
    from arp.config import get_settings

    settings = get_settings()
    connect_args = {} if "connect_timeout" in dsn else {"connect_timeout": _CONNECT_TIMEOUT_SECONDS}
    return create_engine(
        dsn, pool_pre_ping=True, connect_args=connect_args,
        pool_size=settings.postgres_pool_size, max_overflow=settings.postgres_max_overflow,
    )


def ensure_schema(dsn: str) -> dict:
    """Brings a database up to what this codebase's Postgres models define
    -- the pgvector extension, missing tables, missing columns, and any
    unapplied schema step -- idempotently, like every other "bring your own
    external store" setup step here (see e.g. DocumentContentStore's
    CREATE TABLE IF NOT EXISTS). Call once per deployment of a schema
    change (`arp db init-postgres`), not per request.

    Lives in arp/storage/postgres_schema.py, which also offers the
    read-only `schema_report` behind `arp db check-postgres`; re-exported
    here because every existing caller imports it from this module.
    """
    from arp.storage.postgres_schema import ensure_schema as _ensure_schema

    return _ensure_schema(dsn)
