"""Schema setup, evolution and verification for the Postgres store (required:
the system of record), deliberately without Alembic. `ensure_schema` (what
`arp db init-postgres` runs) does, in order:

1. **pre-create steps** (`PRE_CREATE_STEPS`) -- renames legacy tables whose
   names the current models reuse.
2. **create_all** -- missing tables.
3. **additive column reconciliation** -- `ALTER TABLE ... ADD COLUMN` for
   every column a model defines and the database lacks (nullable, no
   constraints; a step adds those where needed).
4. **recorded steps** (`SCHEMA_STEPS`) -- anything reconciliation can't
   infer: constraints, indexes, backfills, views. Each runs once per
   database, is recorded in `schema_migrations`, and is safe to re-run.

Nothing here drops a table or a column, or changes a column's type or
nullability. Tables earlier versions wrote (`company_records`,
`legacy_company_facts`, `document_registry`, `index_checkpoints`,
`engagement_issues`, `engagement_commitments`) stay in place: `arp db import` reads `document_registry` after `ensure_schema` ran.
`schema_report` (what `arp db check-postgres` prints) reports drift, and
counts legacy-keyed rows no registry company matched yet
(`unmatched_company_rows`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from arp.storage.postgres import PostgresExtraNotInstalled, get_engine

if TYPE_CHECKING:
    from sqlalchemy import Connection

_MIGRATIONS_TABLE = "schema_migrations"


@dataclass(frozen=True)
class SchemaStep:
    """One recorded, run-once schema change. `apply` must be safe to call
    against a database that already satisfies it: a step is recorded only
    after it succeeds, so a crash between the DDL and the record means the
    next run calls it again."""

    name: str
    description: str
    apply: Callable[[Connection], None]


def _drop_projection_company_fks(conn: Connection) -> None:
    """Drops the foreign keys from the old projection tables (company_records,
    legacy_company_facts, engagement_issues) to `legacy_companies`: those rows
    came from universe files, so the FK rejected every insert and the
    best-effort hooks swallowed it. Found by catalog lookup, since older
    SQLAlchemy versions named them differently.
    """
    from sqlalchemy import text

    rows = conn.execute(
        text(
            """
            SELECT con.conrelid::regclass::text AS table_name, con.conname AS constraint_name
            FROM pg_constraint con
            JOIN pg_class child ON child.oid = con.conrelid
            JOIN pg_class parent ON parent.oid = con.confrelid
            WHERE con.contype = 'f'
              AND parent.relname = 'legacy_companies'
              AND child.relname IN ('company_records', 'legacy_company_facts', 'engagement_issues')
            """
        )
    ).all()
    for table_name, constraint_name in rows:
        conn.execute(text(f'ALTER TABLE {table_name} DROP CONSTRAINT "{constraint_name}"'))


def _rename_legacy_table(conn: Connection, old: str, new: str, marker: str, renames: tuple[tuple[str, str], ...]) -> None:
    """Renames a legacy-shaped `old` (has column `marker`) to `new`, plus the
    pkey/index/sequence names the new same-named table would collide with."""
    from sqlalchemy import text

    cols = {r[0] for r in conn.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = :t"),
        {"t": old},
    )}
    if marker not in cols:
        return
    conn.execute(text(f"ALTER TABLE {old} RENAME TO {new}"))
    for kind, name in renames:
        legacy = name.replace(old, new, 1)
        if kind == "constraint":
            conn.execute(text(f"ALTER TABLE {new} RENAME CONSTRAINT {name} TO {legacy}"))
        else:
            conn.execute(text(f"ALTER {kind} IF EXISTS {name} RENAME TO {legacy}"))


def _rename_legacy_companies(conn: Connection) -> None:
    _rename_legacy_table(conn, "companies", "legacy_companies", "company_id", (("constraint", "companies_pkey"),))


def _rename_legacy_company_facts(conn: Connection) -> None:
    _rename_legacy_table(
        conn,
        "company_facts",
        "legacy_company_facts",
        "fact_key",
        (
            ("constraint", "company_facts_pkey"),
            ("SEQUENCE", "company_facts_id_seq"),
            ("INDEX", "ix_company_facts_current"),
            ("INDEX", "ix_company_facts_type"),
        ),
    )


def _fields_id_check(conn: Connection) -> None:
    from sqlalchemy import text

    if not conn.execute(text("SELECT 1 FROM pg_constraint WHERE conname = 'ck_fields_field_id'")).first():
        conn.execute(
            text(
                "ALTER TABLE fields ADD CONSTRAINT ck_fields_field_id"
                " CHECK (field_id ~ '^(fld_[a-z0-9]+|prov:[a-z0-9_]+:[a-z0-9_]+)$')"
            )
        )


def _fields_id_check_v2(conn: Connection) -> None:
    from sqlalchemy import text

    conn.execute(text("ALTER TABLE fields DROP CONSTRAINT IF EXISTS ck_fields_field_id"))
    conn.execute(
        text(
            "ALTER TABLE fields ADD CONSTRAINT ck_fields_field_id CHECK (field_id ~ "
            "'^([a-z][a-z0-9_]*|prov:[a-z0-9_]+:[a-z0-9_]+|theme:[^:[:space:]]+|vote:[^:[:space:]]+:[^:[:space:]]+)$')"
        )
    )


def _create_bi_views(conn: Connection) -> None:
    from arp.bi.views import create_bi_views

    create_bi_views(conn)


def _holdings_intake(conn: Connection) -> None:
    """E77: `holdings` holds index rows beside portfolio rows. Drops the FK
    to `portfolios` (an index is no portfolio; found by catalog lookup, as in
    step 0001), lets the money columns be NULL (an index row has weights, a
    portfolio row may lack an FX rate), marks old rows as portfolio rows,
    widens the unique key by `kind`, and re-creates the BI views so they
    stay portfolio-only (step 0002 never re-runs)."""
    from sqlalchemy import text

    rows = conn.execute(
        text(
            """
            SELECT con.conname FROM pg_constraint con
            JOIN pg_class child ON child.oid = con.conrelid
            JOIN pg_class parent ON parent.oid = con.confrelid
            WHERE con.contype = 'f' AND child.relname = 'holdings' AND parent.relname = 'portfolios'
            """
        )
    ).scalars().all()
    for name in rows:
        conn.execute(text(f'ALTER TABLE holdings DROP CONSTRAINT "{name}"'))
    conn.execute(text("ALTER TABLE holdings DROP CONSTRAINT IF EXISTS uq_holdings_portfolio_security_date"))
    for column in ("quantity", "price", "market_value", "market_value_eur", "fx_rate_to_eur"):
        conn.execute(text(f"ALTER TABLE holdings ALTER COLUMN {column} DROP NOT NULL"))
    # The column was added nullable, without a default, by reconciliation.
    conn.execute(text("ALTER TABLE holdings ALTER COLUMN kind SET DEFAULT 'portfolio'"))
    conn.execute(text("UPDATE holdings SET kind = 'portfolio' WHERE kind IS NULL"))
    conn.execute(text("ALTER TABLE holdings ALTER COLUMN kind SET NOT NULL"))
    if not conn.execute(text("SELECT 1 FROM pg_constraint WHERE conname = 'uq_holdings_kind_holder_security_date'")).first():
        conn.execute(
            text(
                "ALTER TABLE holdings ADD CONSTRAINT uq_holdings_kind_holder_security_date"
                " UNIQUE (kind, portfolio_id, security_id, as_of_date)"
            )
        )
    _create_bi_views(conn)


def _run_store_tables(conn: Connection) -> None:
    """Task 5's RunStore columns on tables created before them. Nothing wrote these tables
    before the RunStore did, so the NOT NULLs need no backfill."""
    from sqlalchemy import text

    for sql in (
        "ALTER TABLE run_companies ALTER COLUMN ordinal SET NOT NULL",
        "ALTER TABLE run_companies ALTER COLUMN ref SET NOT NULL",
        "ALTER TABLE run_results ALTER COLUMN result_key SET NOT NULL",
        "ALTER TABLE run_results ALTER COLUMN company_id DROP NOT NULL",
        "ALTER TABLE run_results DROP CONSTRAINT IF EXISTS uq_run_results",
        "ALTER TABLE review_items ALTER COLUMN company_id DROP NOT NULL",
        "ALTER TABLE review_decisions ALTER COLUMN run_id SET NOT NULL",
        "ALTER TABLE review_decisions ALTER COLUMN row SET NOT NULL",
        "ALTER TABLE review_decisions ALTER COLUMN review_item_id DROP NOT NULL",
        "ALTER TABLE review_decisions ALTER COLUMN decision DROP NOT NULL",
        "ALTER TABLE review_cosigns ALTER COLUMN run_id SET NOT NULL",
        "ALTER TABLE review_cosigns ALTER COLUMN row SET NOT NULL",
        "ALTER TABLE review_cosigns ALTER COLUMN review_item_id DROP NOT NULL",
    ):
        conn.execute(text(sql))
    if not conn.execute(text("SELECT 1 FROM pg_constraint WHERE conname = 'uq_run_results_key'")).first():
        conn.execute(text("ALTER TABLE run_results ADD CONSTRAINT uq_run_results_key UNIQUE (run_id, result_key)"))


def _documents_content_index(conn: Connection) -> None:
    from sqlalchemy import text

    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_content ON documents (content_key)"))


# Legacy-keyed tables: table -> (registry-company column, then the columns naming the company:
# issuer key, issuer scheme, ISIN, universe id). fact_events copies from its published fact.
_REKEYED: dict[str, tuple[str, str | None, str | None, str | None, str | None]] = {
    "holdings": ("company_id", "issuer_key", "issuer_scheme", "isin", None),
    "securities": ("company_uuid", None, None, "isin", "company_id"),
    "security_resolutions": ("company_uuid", None, None, None, "company_id"),
    "releases": ("company_id", "issuer_key", "issuer_scheme", None, None),
    "published_facts": ("company_id", "issuer_key", "issuer_scheme", None, None),
}
_REKEY_ARGS = ("issuer_key", "issuer_scheme", "isin", "universe_id")


def _review_item_links(conn: Connection) -> None:
    """review_item_observations for items queued before the table: as `observations.queue_item` links them."""
    from sqlalchemy import text

    conn.execute(text(
        "INSERT INTO review_item_observations (review_item_id, observation_id)"
        " SELECT id, observation_id FROM review_items WHERE observation_id IS NOT NULL ON CONFLICT DO NOTHING"
    ))
    conn.execute(text(
        "INSERT INTO review_item_observations (review_item_id, observation_id)"
        " SELECT i.id, o.id FROM review_items i JOIN field_observations o"
        " ON o.run_id = i.run_id AND o.company_id = i.company_id AND o.route = 'review'"
        " WHERE i.observation_id IS NULL AND i.item_key = i.payload->>'company_id' ON CONFLICT DO NOTHING"
    ))


def rekey_company_ids(conn: Connection) -> None:
    """Sets the registry company on every legacy-keyed row that has none yet (rules:
    `arp.db.companies.company_for`). Rows that match nothing keep NULL; `schema_report` counts them.
    Re-runnable: `arp db import` calls it again once the companies exist."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from arp.db.companies import company_for

    session = Session(bind=conn)
    for table, (target, *sources) in _REKEYED.items():
        cols = {arg: col for arg, col in zip(_REKEY_ARGS, sources, strict=True) if col}
        where = " AND ".join(f"{col} IS NOT DISTINCT FROM :{arg}" for arg, col in cols.items())
        # ponytail: one lookup and one UPDATE per distinct key; a set-based UPDATE if tables grow past ~1e5 keys
        for row in conn.execute(text(f"SELECT DISTINCT {', '.join(cols.values())} FROM {table} WHERE {target} IS NULL")):
            args = dict(zip(cols, row, strict=True))
            company = company_for(session, **args)
            if company is not None:
                conn.execute(
                    text(f"UPDATE {table} SET {target} = :company WHERE {target} IS NULL AND {where}"),
                    {"company": company, **args},
                )
    conn.execute(text(
        "UPDATE fact_events e SET company_id = f.company_id FROM published_facts f"
        " WHERE e.company_id IS NULL AND f.fact_id = e.fact_id AND f.company_id IS NOT NULL"
    ))
    session.close()


def _phase1_rekey(conn: Connection) -> None:
    """Spec §2.8: the company column's FK on tables that had the column added by reconciliation (which
    adds no constraints), the company-key index on published_facts, then the backfill. issuer_key,
    issuer_scheme and the legacy tables stay: `arp db import` still reads them."""
    from sqlalchemy import text

    for table, (target, *_rest) in (*_REKEYED.items(), ("fact_events", ("company_id",))):
        name = f"fk_{table}_{target}"
        if not conn.execute(text("SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": name}).first():
            conn.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({target}) REFERENCES companies (id)"))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_published_facts_company_key ON published_facts (company_id, field_id, period_end, basis)"
    ))
    rekey_company_ids(conn)


def unmatched_company_rows(conn: Connection) -> dict[str, int]:
    """Legacy-keyed rows no company matched yet, per table (tables with none are left out)."""
    from sqlalchemy import inspect, text

    inspector = inspect(conn)
    out = {}
    for table, target in sorted([(t, cols[0]) for t, cols in _REKEYED.items()] + [("fact_events", "company_id")]):
        if inspector.has_table(table) and target in {c["name"] for c in inspector.get_columns(table)}:
            n = conn.execute(text(f"SELECT count(*) FROM {table} WHERE {target} IS NULL")).scalar()
            if n:
                out[table] = n
    return out


# Run before create_all, so a legacy-shaped table does not shadow a new one of the same name.
PRE_CREATE_STEPS: tuple[SchemaStep, ...] = (
    SchemaStep("0005_rename_legacy_companies", "companies -> legacy_companies", _rename_legacy_companies),
    SchemaStep("0006_rename_legacy_company_facts", "company_facts -> legacy_company_facts", _rename_legacy_company_facts),
)

# Ordered; append new steps, never edit or reorder an existing one (a
# database that already recorded it will not run it again).
SCHEMA_STEPS: tuple[SchemaStep, ...] = (
    SchemaStep(
        name="0001_drop_projection_company_fks",
        description="Drop company_records/company_facts/engagement_issues -> companies foreign keys",
        apply=_drop_projection_company_fks,
    ),
    SchemaStep(
        name="0002_create_bi_views",
        description="Create the bi schema and the views the BI tool reads",
        apply=_create_bi_views,
    ),
    SchemaStep(
        name="0003_holdings_intake",
        description="Index holdings beside portfolio holdings: kind, nullable money columns, no FK to portfolios",
        apply=_holdings_intake,
    ),
    SchemaStep(
        name="0004_bi_published_views",
        description="Re-create the bi views so the datasets published into bi_published are readable",
        apply=_create_bi_views,
    ),
    SchemaStep(
        name="fields_id_check",
        description="CHECK on fields.field_id: fld_<id> or prov:<source>:<metric>",
        apply=_fields_id_check,
    ),
    SchemaStep(
        name="fields_id_check_v2",
        description="field_id CHECK: slug, prov:<source>:<metric>, theme:<id> or vote:<a>:<b>",
        apply=_fields_id_check_v2,
    ),
    SchemaStep(
        name="run_store_tables",
        description="RunStore columns: run_companies ref/ordinal, run_results result_key, decision/cosign rows",
        apply=_run_store_tables,
    ),
    SchemaStep(
        name="documents_content_index",
        description="Index documents.content_key (list_by_content_keys filters on it)",
        apply=_documents_content_index,
    ),
    SchemaStep(
        name="bi_views_company_foundation",
        description="bi.company_facts/_pending, run_records and documents read company_facts, run_results and documents",
        apply=_create_bi_views,
    ),
    SchemaStep(
        name="phase1_rekey",
        description="company_id (registry UUID) on holdings/securities/resolutions/releases/published facts/events,"
        " backfilled from LEI, UNIVERSE, ISIN and INTERNAL-UUID keys",
        apply=_phase1_rekey,
    ),
    SchemaStep(
        name="bi_views_universe_id",
        description="bi fact/run/document views: company_id is the universe id again; company_uuid (and basis) appended",
        apply=_create_bi_views,
    ),
    SchemaStep(
        name="review_item_links",
        description="review_item_observations backfilled: value items to their observation, whole-record items to"
        " their run and company's REVIEW observations",
        apply=_review_item_links,
    ),
)


def _sqlalchemy():
    try:
        import sqlalchemy
    except ImportError as exc:  # pragma: no cover - exercised only without the optional extra
        raise PostgresExtraNotInstalled(exc) from exc
    return sqlalchemy


def _ensure_migrations_table(conn: Connection) -> None:
    from sqlalchemy import text

    conn.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {_MIGRATIONS_TABLE} ("
            " name TEXT PRIMARY KEY,"
            " applied_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
    )


def _applied_step_names(conn: Connection) -> set[str]:
    from sqlalchemy import text

    _ensure_migrations_table(conn)
    return {row[0] for row in conn.execute(text(f"SELECT name FROM {_MIGRATIONS_TABLE}")).all()}


def _missing_columns(conn: Connection) -> list[tuple[str, str]]:
    """(table, column) pairs the models define and the database lacks,
    for tables that already exist."""
    from sqlalchemy import inspect

    from arp.storage.postgres_models import Base

    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())
    missing: list[tuple[str, str]] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all's job, not ours
        have = {col["name"] for col in inspector.get_columns(table.name)}
        missing.extend((table.name, column.name) for column in table.columns if column.name not in have)
    return missing


def _add_missing_columns(conn: Connection) -> list[tuple[str, str]]:
    from sqlalchemy import text

    from arp.storage.postgres_models import Base

    added = []
    for table_name, column_name in _missing_columns(conn):
        table = Base.metadata.tables[table_name]
        column = table.columns[column_name]
        ddl_type = column.type.compile(dialect=conn.dialect)
        # Added nullable regardless of the model's nullability: existing
        # rows have no value for it, so NOT NULL without a default would
        # fail outright. Tightening it afterwards is a data decision, and
        # schema_report flags the difference.
        conn.execute(text(f'ALTER TABLE {table_name} ADD COLUMN "{column_name}" {ddl_type}'))
        added.append((table_name, column_name))
    return added


def _run_steps(conn: Connection, steps: tuple[SchemaStep, ...], applied: set[str], done: list[str]) -> None:
    from sqlalchemy import text

    for step in steps:
        if step.name in applied:
            continue
        step.apply(conn)
        conn.execute(text(f"INSERT INTO {_MIGRATIONS_TABLE} (name) VALUES (:name) ON CONFLICT DO NOTHING"), {"name": step.name})
        done.append(step.name)


def ensure_schema(dsn: str) -> dict:
    """Brings a database up to what the models define, idempotently: the
    pgvector extension, any missing tables, any missing columns, then any
    unapplied step from SCHEMA_STEPS. Safe to run against a fresh
    database, one created before this module existed, or one that is
    already current (then it changes nothing). Call it from `arp db
    init-postgres`, not per request.

    Returns what it did -- `{"tables_created": [...], "columns_added":
    [...], "steps_applied": [...]}` -- so the CLI can report it instead of
    claiming success without detail.
    """
    _sqlalchemy()
    from sqlalchemy import inspect, text

    import arp.db.models  # noqa: F401  (registers the company-foundation tables on Base)
    from arp.storage.postgres_models import Base

    engine = get_engine(dsn)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    steps_applied: list[str] = []
    with engine.begin() as conn:
        applied = _applied_step_names(conn)
        _run_steps(conn, PRE_CREATE_STEPS, applied, steps_applied)

    with engine.connect() as conn:
        before = set(inspect(conn).get_table_names())

    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        after = set(inspect(conn).get_table_names())
        columns_added = _add_missing_columns(conn)
        _run_steps(conn, SCHEMA_STEPS, _applied_step_names(conn), steps_applied)

    return {
        "tables_created": sorted(after - before),
        "columns_added": [f"{t}.{c}" for t, c in columns_added],
        "steps_applied": steps_applied,
    }


def _gaps(conn: Connection, existing_tables: set[str]) -> tuple[list[str], list[str], set[str]]:
    """(missing tables, pending step names, applied step names)."""
    import arp.db.models  # noqa: F401
    from arp.storage.postgres_models import Base

    missing = sorted({t.name for t in Base.metadata.sorted_tables} - existing_tables)
    applied = _applied_step_names(conn) if _MIGRATIONS_TABLE in existing_tables else set()
    return missing, [s.name for s in (*PRE_CREATE_STEPS, *SCHEMA_STEPS) if s.name not in applied], applied


def schema_gaps(dsn: str) -> tuple[list[str], list[str]]:
    """(missing tables, pending steps) as `schema_report` lists them, without its column and row scans:
    the startup check (`arp.db.session.require_cutover`)."""
    _sqlalchemy()
    from sqlalchemy import inspect

    with get_engine(dsn).connect() as conn:
        missing, pending, _ = _gaps(conn, set(inspect(conn).get_table_names()))
    return missing, pending


def schema_report(dsn: str) -> dict:
    """Read-only: what this database has versus what the models define.
    Changes nothing, so it is safe to point at production.

    `current` is True when nothing is missing and no step is pending --
    i.e. every query this codebase issues will find its table, column and
    constraint. `drift` lists differences this module will not act on by
    itself (a table or column the models no longer define, a nullability
    mismatch left behind by an added column); those are for an operator to
    resolve.
    """
    _sqlalchemy()
    from sqlalchemy import inspect, text

    import arp.db.models  # noqa: F401
    from arp.storage.postgres_models import Base

    engine = get_engine(dsn)
    with engine.connect() as conn:
        inspector = inspect(conn)
        existing_tables = set(inspector.get_table_names())
        expected_tables = {t.name for t in Base.metadata.sorted_tables}
        missing_tables, pending_steps, applied = _gaps(conn, existing_tables)
        missing_columns = [f"{t}.{c}" for t, c in _missing_columns(conn)]

        has_vector = bool(
            conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).first()
        )

        unmatched = unmatched_company_rows(conn) if "companies" in existing_tables else {}
        drift: list[str] = []
        for table_name in sorted(existing_tables & expected_tables):
            table = Base.metadata.tables[table_name]
            db_columns = {col["name"]: col for col in inspector.get_columns(table_name)}
            for column in table.columns:
                db_column = db_columns.get(column.name)
                if db_column is None:
                    continue  # already reported as missing
                if db_column["nullable"] and not column.nullable:
                    drift.append(f"{table_name}.{column.name} is nullable in the database, NOT NULL in the model")
            for name in sorted(set(db_columns) - {c.name for c in table.columns}):
                drift.append(f"{table_name}.{name} exists in the database but not in the models")

    return {
        "vector_extension": has_vector,
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "applied_steps": sorted(applied),
        "pending_steps": pending_steps,
        "drift": drift,
        "unmatched_company_rows": unmatched,
        "current": not (missing_tables or missing_columns or pending_steps or not has_vector),
    }
