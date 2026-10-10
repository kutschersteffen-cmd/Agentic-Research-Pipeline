"""Engine and transaction helpers for the company-foundation tables."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from arp.config import get_settings
from arp.storage.postgres import get_engine


def require_dsn(settings) -> str:
    if not settings.postgres_dsn:
        raise RuntimeError("ARP_POSTGRES_DSN is required: Postgres is the system of record.")
    return settings.postgres_dsn


def require_postgres(settings) -> str:
    """Startup check (app lifespan, CLI root): a DSN is set and Postgres answers `SELECT 1`.
    The error names the DSN tried, password masked."""
    from sqlalchemy import make_url, text

    dsn = require_dsn(settings)
    try:
        with engine(dsn).connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - any failure to connect stops startup
        reason = str(getattr(exc, "orig", None) or exc).splitlines()[0]
        masked = make_url(dsn).render_as_string(hide_password=True)
        raise RuntimeError(f"Postgres unreachable at {masked}: {reason}") from exc
    return dsn


def engine(dsn: str | None = None) -> Engine:
    return get_engine(dsn or require_dsn(get_settings()))


@contextmanager
def transaction(dsn: str | None = None) -> Iterator[Session]:
    """Session that commits on exit and rolls back on exception."""
    with Session(engine(dsn)) as session, session.begin():
        yield session
