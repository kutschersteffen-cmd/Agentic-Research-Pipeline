"""The `bi` schema: the only part of the database the BI tool's read-only
role (`bi_reader`) may touch. Views flatten the relational tables into the
datasets in `catalog.VIEW_DATASETS` (the column lists here must match it;
tests assert that), expose real types instead of ISO strings, and leave
out raw JSON payloads.

Fact value shape (checked against `fact_candidates` in
postgres_company_facts_projection.py): `company_facts.value` is the whole
pipeline row/match/vote dict, with no guaranteed numeric field. Where a
pipeline reports a scalar it is `value->'value'`, so `value_num` is that
key when `jsonb_typeof` is 'number' and NULL otherwise; `value_text` is the
same key when it is a JSON string. Anything else stays NULL, never an error.

Every view is `CREATE OR REPLACE`, so `create_bi_views` is safe to re-run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy import Connection

# Keep in step with PLACEHOLDERS in superset/superset_config.py (that file cannot import arp).
PLACEHOLDER_SECRETS = {"change-me-dev-only", "CHANGE_ME_SECRET_KEY", "test-guest-secret-change-me"}
ROLE = "bi_reader"

# Date/timestamp columns are text in the base tables and may be '' or junk.
# A plain cast raises on those (and a regex guard alone still lets
# '2026-13-45' through), so the cast is wrapped in a function that
# swallows the error and returns NULL.
_SAFE_CAST_FUNCTIONS = (
    r"""
    CREATE OR REPLACE FUNCTION bi.safe_date(s text) RETURNS date LANGUAGE plpgsql STABLE AS $$
    BEGIN
        IF s IS NULL OR s !~ '^\d{4}-\d{2}-\d{2}' THEN RETURN NULL; END IF;
        RETURN s::date;
    EXCEPTION WHEN others THEN RETURN NULL;
    END $$
    """,
    r"""
    CREATE OR REPLACE FUNCTION bi.safe_ts(s text) RETURNS timestamptz LANGUAGE plpgsql STABLE AS $$
    BEGIN
        IF s IS NULL OR s !~ '^\d{4}-\d{2}-\d{2}' THEN RETURN NULL; END IF;
        RETURN s::timestamptz;
    EXCEPTION WHEN others THEN RETURN NULL;
    END $$
    """,
)

_FACT_SELECT = """
    SELECT company_id, fact_key, fact_type,
           bi.safe_date(NULLIF(as_of, '')) AS as_of,
           CASE WHEN jsonb_typeof(value->'value') = 'number' AND abs((value->>'value')::numeric) < 1e300
                THEN (value->>'value')::double precision END AS value_num,
           CASE WHEN jsonb_typeof(value->'value') = 'string' THEN value->>'value' END AS value_text,
           status, confidence, reviewer,
           bi.safe_ts(valid_from) AS valid_from
    FROM company_facts
    WHERE is_current AND status IN ({statuses})
"""

_HOLDINGS_SELECT = """
    SELECT h.portfolio_id, p.name AS portfolio_name, bi.safe_date(h.as_of_date) AS as_of_date,
           h.security_id, s.name AS security_name, s.isin, s.asset_class, s.currency,
           s.company_id, c.name AS company_name, c.sector, c.country,
           h.quantity, h.market_value_eur, h.weight_pct,
           (SELECT substr(t, 9) FROM unnest(p.tags) t WHERE t LIKE 'project:%' LIMIT 1) AS project_id
    FROM holdings h
    JOIN portfolios p ON p.portfolio_id = h.portfolio_id
    LEFT JOIN securities s ON s.security_id = h.security_id
    LEFT JOIN companies c ON c.company_id = s.company_id
"""

_VIEWS = {
    # Latest valid snapshot per portfolio, found in one pass (not a per-row
    # subquery). Max over valid dates only, so a malformed as_of_date string
    # cannot win the "latest" comparison.
    "holdings": _HOLDINGS_SELECT
    + """
        JOIN (
            SELECT portfolio_id, max(bi.safe_date(as_of_date)) AS d FROM holdings GROUP BY portfolio_id
        ) latest ON latest.portfolio_id = h.portfolio_id AND bi.safe_date(h.as_of_date) = latest.d
    """,
    # Every snapshot; junk dates (NULL after the safe cast) are left out.
    "holdings_history": _HOLDINGS_SELECT + " WHERE bi.safe_date(h.as_of_date) IS NOT NULL",
    "company_facts": _FACT_SELECT.format(statuses="'approved', 'edited', 'auto_approved'"),
    "company_facts_pending": _FACT_SELECT.format(statuses="'pending_review'"),
    "run_records": """
        SELECT run_id, run_type, company_id, needs_review, overall_confidence,
               bi.safe_ts(generated_at) AS generated_at
        FROM company_records
    """,
    "documents": """
        SELECT doc_id, company_id, doc_type, title, source_url,
               bi.safe_ts(first_seen_at) AS first_seen_at, bi.safe_ts(last_seen_at) AS last_seen_at
        FROM document_registry
    """,
}


def create_bi_views(conn: Connection) -> None:
    from sqlalchemy import text

    conn.execute(text("CREATE SCHEMA IF NOT EXISTS bi"))
    for ddl in _SAFE_CAST_FUNCTIONS:
        conn.execute(text(ddl))
    for name, select in _VIEWS.items():
        # CREATE OR REPLACE VIEW cannot drop or reorder columns; fine while
        # the column list is stable, and the tests pin it to the catalog.
        conn.execute(text(f"CREATE OR REPLACE VIEW bi.{name} AS {select}"))


def ensure_reader_role(conn: Connection, password: str, role: str = ROLE) -> None:
    """Creates or updates `role` (default `bi_reader`): LOGIN, no access to
    the base tables, SELECT on the `bi` views only. Idempotent. The views run
    with their owner's rights, so the role needs nothing on `public`. `role`
    is a trusted identifier (tests pass their own so they never touch the real one)."""
    from sqlalchemy import text

    conn.execute(
        text(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN CREATE ROLE {role} LOGIN; END IF; END $$"
        )
    )
    alter = conn.execute(
        text(f"SELECT format('ALTER ROLE {role} WITH LOGIN PASSWORD %L', CAST(:pw AS text))"), {"pw": password}
    ).scalar()
    # The formatted statement embeds the password; escape ':' so text() does
    # not read ':name' inside it as a bind parameter.
    conn.execute(text(alter.replace(":", "\\:")))
    conn.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}"))
    conn.execute(text(f"REVOKE ALL ON SCHEMA public FROM {role}"))
    conn.execute(text(f"GRANT USAGE ON SCHEMA bi TO {role}"))
    conn.execute(text(f"GRANT SELECT ON ALL TABLES IN SCHEMA bi TO {role}"))
