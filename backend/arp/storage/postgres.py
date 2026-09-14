from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy import Engine


class PostgresNotConfigured(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "Settings.postgres_dsn is not set. The Postgres/pgvector store is entirely opt-in -- "
            "set ARP_POSTGRES_DSN (e.g. postgresql+psycopg://user:pass@host:5432/arp) to enable it. "
            "The file-based stores work with no configuration at all and are unaffected either way."
        )


class PostgresExtraNotInstalled(RuntimeError):
    def __init__(self, exc: Exception) -> None:
        super().__init__(
            "postgres_dsn is set but sqlalchemy/psycopg/pgvector aren't installed. Install the optional "
            f"extra: pip install -e '.[postgres]'. Original import error: {exc}"
        )


@lru_cache
def get_engine(dsn: str) -> Engine:
    """One pooled Engine per DSN for the process lifetime -- SQLAlchemy's
    own recommended pattern (an Engine already owns a connection pool;
    building a new one per call would defeat that). Imports SQLAlchemy
    lazily so the rest of this codebase never pays an import cost, let
    alone a hard dependency, for a store nobody has opted into.
    """
    try:
        from sqlalchemy import create_engine
    except ImportError as exc:  # pragma: no cover - exercised only without the optional extra
        raise PostgresExtraNotInstalled(exc) from exc
    return create_engine(dsn, pool_pre_ping=True)


def ensure_schema(dsn: str) -> None:
    """Creates every table this codebase's Postgres models define, if not
    already present (idempotent, like every other "bring your own external
    store" setup step in this codebase -- see e.g. DocumentContentStore's
    CREATE TABLE IF NOT EXISTS). Also ensures the pgvector extension exists
    when the embeddings table needs it. Call once per fresh database
    (`arp db init-postgres`), not per request.
    """
    try:
        from sqlalchemy import text
    except ImportError as exc:  # pragma: no cover
        raise PostgresExtraNotInstalled(exc) from exc

    from arp.storage.postgres_models import Base

    engine = get_engine(dsn)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
