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


def engine(dsn: str | None = None) -> Engine:
    return get_engine(dsn or require_dsn(get_settings()))


@contextmanager
def transaction(dsn: str | None = None) -> Iterator[Session]:
    """Session that commits on exit and rolls back on exception."""
    with Session(engine(dsn)) as session, session.begin():
        yield session
