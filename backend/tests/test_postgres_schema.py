"""`arp db init-postgres` / `arp db check-postgres`, against a real
instance.

`ensure_schema` used to be `create_all` alone, which creates missing
*tables* and nothing else -- no added columns, no way to drop a constraint,
and no record of what a given database had. So these tests are mostly about
a database that already exists and is *behind*: the state every deployment
lands in after a codebase upgrade.

Skipped without ARP_TEST_POSTGRES_DSN, like the other Postgres suites.
"""

from __future__ import annotations

import os

import pytest

DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set -- opt-in Postgres integration test")


@pytest.fixture
def current_schema():
    """A database at the current schema, restored to that state afterwards
    however a test mangles it."""
    from arp.storage.postgres_schema import ensure_schema

    ensure_schema(DSN)
    yield
    ensure_schema(DSN)


def _execute(sql: str) -> list:
    """Runs one statement and returns its rows, or [] for DDL (which
    returns no result set)."""
    from sqlalchemy import text

    from arp.storage.postgres import get_engine

    with get_engine(DSN).begin() as conn:
        result = conn.execute(text(sql))
        return result.all() if result.returns_rows else []


def test_a_current_database_reports_current_and_ensure_changes_nothing(current_schema):
    from arp.storage.postgres_schema import ensure_schema, schema_report

    report = schema_report(DSN)
    assert report["current"] is True
    assert report["missing_tables"] == []
    assert report["missing_columns"] == []
    assert report["pending_steps"] == []
    assert report["vector_extension"] is True

    result = ensure_schema(DSN)
    assert result == {"tables_created": [], "columns_added": [], "steps_applied": []}


def test_a_missing_table_is_reported_then_created(current_schema):
    """The one case `create_all` already handled -- kept honest here
    because the report has to agree with it."""
    from arp.storage.postgres_schema import ensure_schema, schema_report

    _execute("DROP TABLE IF EXISTS engagement_commitments")

    report = schema_report(DSN)
    assert "engagement_commitments" in report["missing_tables"]
    assert report["current"] is False

    assert "engagement_commitments" in ensure_schema(DSN)["tables_created"]
    assert schema_report(DSN)["current"] is True


def test_a_missing_column_is_reported_then_added(current_schema):
    """What `create_all` silently does *not* do, and what an operator used
    to discover as an UndefinedColumn error at query time."""
    from arp.storage.postgres_schema import ensure_schema, schema_report

    _execute("ALTER TABLE company_records DROP COLUMN needs_review")

    report = schema_report(DSN)
    assert "company_records.needs_review" in report["missing_columns"]
    assert report["current"] is False

    assert "company_records.needs_review" in ensure_schema(DSN)["columns_added"]
    report = schema_report(DSN)
    assert report["missing_columns"] == []
    assert report["current"] is True


def test_a_column_the_models_dropped_is_reported_as_drift_not_removed(current_schema):
    """Deliberately not acted on: dropping a column destroys data, so the
    report names it and a human decides."""
    from arp.storage.postgres_schema import ensure_schema, schema_report

    _execute("ALTER TABLE company_records ADD COLUMN legacy_note TEXT")
    try:
        report = schema_report(DSN)
        assert any("company_records.legacy_note" in note for note in report["drift"])
        # Still "current": every query this codebase issues works fine.
        assert report["current"] is True

        ensure_schema(DSN)
        assert _execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name='company_records' AND column_name='legacy_note'"
        ), "ensure_schema must not drop a column it doesn't know about"
    finally:
        _execute("ALTER TABLE company_records DROP COLUMN IF EXISTS legacy_note")


def test_a_recorded_step_is_applied_once_and_only_once(current_schema):
    """Steps are run-once and recorded, which is what makes "is this
    database current?" answerable at all."""
    from arp.storage.postgres_schema import SCHEMA_STEPS, ensure_schema, schema_report

    step_names = [step.name for step in SCHEMA_STEPS]
    assert schema_report(DSN)["applied_steps"] == sorted(step_names)

    _execute("DELETE FROM schema_migrations")

    report = schema_report(DSN)
    assert report["pending_steps"] == step_names
    assert report["current"] is False

    assert ensure_schema(DSN)["steps_applied"] == step_names
    assert ensure_schema(DSN)["steps_applied"] == []  # not a second time


def test_the_projection_fk_step_is_idempotent_against_a_legacy_database(current_schema):
    """The step that exists today: a database created before the foreign
    keys were removed carries them, and re-adding them here is the only
    honest way to test their removal."""
    from arp.storage.postgres_schema import ensure_schema

    _execute(
        "ALTER TABLE company_records ADD CONSTRAINT company_records_company_id_fkey "
        "FOREIGN KEY (company_id) REFERENCES companies(company_id)"
    )
    _execute("DELETE FROM schema_migrations WHERE name = '0001_drop_projection_company_fks'")

    ensure_schema(DSN)

    assert (
        _execute(
            "SELECT 1 FROM pg_constraint WHERE conname = 'company_records_company_id_fkey'"
        )
        == []
    )
    # And running the step against a database that never had it is a no-op,
    # not an error.
    _execute("DELETE FROM schema_migrations WHERE name = '0001_drop_projection_company_fks'")
    ensure_schema(DSN)
