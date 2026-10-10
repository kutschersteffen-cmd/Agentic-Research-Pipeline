"""Shared setup for the opt-in Postgres suites.

Every one of them points at the same scratch database, and several assert
on *unfiltered* queries -- "total market value by sector across all
portfolios" is exactly the question the relational backend exists to
answer, so narrowing those assertions to the rows one test happens to have
written would stop testing the thing. That makes an empty starting state
part of each test's setup, not just polite cleanup: one row left behind by
another suite (or by a developer's manual `arp` command against the same
scratch database) silently changes a total.

So `reset_postgres_tables` is called before *and* after each such test.
Truncating rather than dropping keeps the schema (and the recorded schema
steps) intact, which is what the tests are running against.
"""

from __future__ import annotations

def reset_postgres_tables(dsn: str) -> None:
    """Empties every table the models define in one TRUNCATE, leaving the
    schema in place. `schema_migrations` is deliberately NOT emptied (it is
    not a model table): it records which schema steps this database has had
    applied, and wiping it would make the next `ensure_schema` re-run them."""
    import arp.db.models  # noqa: F401  (register every table on Base)
    from sqlalchemy import inspect, text

    from arp.storage.postgres import get_engine
    from arp.storage.postgres_models import Base

    engine = get_engine(dsn)
    with engine.begin() as conn:
        existing = set(inspect(conn).get_table_names())
        names = [t.name for t in Base.metadata.sorted_tables if t.name in existing and t.name != "schema_migrations"]
        if names:
            conn.execute(text(f"TRUNCATE {', '.join(names)} RESTART IDENTITY CASCADE"))
