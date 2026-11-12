"""Stewardship and vote-ledger tables: created by ensure_schema, idempotent, legacy tables untouched."""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from arp.storage.postgres import get_engine
from arp.storage.postgres_models import STEWARDSHIP_TABLES
from arp.storage.postgres_schema import ensure_schema


def _snapshot(dsn):
    engine = get_engine(dsn)
    insp = inspect(engine)
    with engine.connect() as conn:
        return {
            t: (
                [c["name"] for c in insp.get_columns(t)],
                conn.execute(text(f"SELECT count(*) FROM {t}")).scalar(),
            )
            for t in STEWARDSHIP_TABLES
        }


def test_init_creates_tables(pg):
    ensure_schema(pg)
    ensure_schema(pg)
    assert set(STEWARDSHIP_TABLES) <= set(inspect(get_engine(pg)).get_table_names())
    assert len(STEWARDSHIP_TABLES) == 11


def test_second_init_changes_nothing(pg):
    ensure_schema(pg)
    before = _snapshot(pg)
    ensure_schema(pg)
    assert _snapshot(pg) == before


def test_legacy_tables_untouched(pg):
    engine = get_engine(pg)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS engagement_issues (issue_id TEXT PRIMARY KEY, company_id TEXT)"))
        conn.execute(
            text("CREATE TABLE IF NOT EXISTS engagement_commitments (commitment_id TEXT PRIMARY KEY, issue_id TEXT)")
        )
        conn.execute(text("INSERT INTO engagement_issues VALUES ('iss_1', 'c1') ON CONFLICT DO NOTHING"))
        conn.execute(text("INSERT INTO engagement_commitments VALUES ('cmt_1', 'iss_1') ON CONFLICT DO NOTHING"))

    def counts():
        with engine.connect() as conn:
            return [
                conn.execute(text(f"SELECT count(*) FROM {t}")).scalar()
                for t in ("engagement_issues", "engagement_commitments")
            ]

    try:
        assert counts() == [1, 1]
        ensure_schema(pg)
        assert counts() == [1, 1]
    finally:  # not model tables, so the pg fixture never empties them
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE engagement_issues, engagement_commitments"))


def test_unique_source_external_id(pg):
    ensure_schema(pg)
    engine = get_engine(pg)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO stw_companies (company_id, source) VALUES ('c1', 'app')"))
        ins = text(
            "INSERT INTO stw_engagements (engagement_id, source, external_id, company_id) VALUES (:i, 'excel', 'x1', 'c1')"
        )
        conn.execute(ins, {"i": "iss_1"})
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(ins, {"i": "iss_2"})
