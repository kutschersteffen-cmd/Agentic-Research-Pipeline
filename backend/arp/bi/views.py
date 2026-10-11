"""The `bi` schema: the only part of the database the BI tool's read-only
role (`bi_reader`) may touch. Views flatten the relational tables into the
datasets in `catalog.VIEW_DATASETS` (the column lists here must match it;
tests assert that), expose real types instead of ISO strings, and leave
out raw JSON payloads.

The fact, run and document views read the company-foundation tables
(`company_facts`, `run_results`, `documents`) under the column names and
types the earlier projection tables had, so existing Superset datasets keep
working; `company_id` there is the registry UUID as text. A fact's `value`
is the field's JSON value: `value_num` is it when `jsonb_typeof` is
'number', `value_text` when it is a string, otherwise NULL, never an error.

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
    SELECT f.company_id::varchar AS company_id, f.field_id::varchar AS fact_key, d.data_type::varchar AS fact_type,
           f.period_end AS as_of,
           CASE WHEN jsonb_typeof(f.value) = 'number' AND abs((f.value #>> '{{}}')::numeric) < 1e300
                THEN (f.value #>> '{{}}')::double precision END AS value_num,
           CASE WHEN jsonb_typeof(f.value) = 'string' THEN f.value #>> '{{}}' END AS value_text,
           f.status::varchar AS status, o.confidence, r.reviewer::varchar AS reviewer,
           f.valid_from
    FROM company_facts f
    JOIN field_observations o ON o.id = f.observation_id
    LEFT JOIN field_definitions d ON d.field_id = o.field_id AND d.version = o.field_version
    LEFT JOIN review_decisions r ON r.id = f.decision_id
    WHERE f.valid_to IS NULL AND f.status::text IN ({statuses})
"""

_HOLDINGS_SELECT = """
    SELECT h.portfolio_id, p.name AS portfolio_name, bi.safe_date(h.as_of_date) AS as_of_date,
           h.security_id, s.name AS security_name, s.isin, s.asset_class, s.currency,
           s.company_id, c.name AS company_name, c.sector, c.country,
           h.quantity, h.market_value_eur, h.weight_pct,
           (SELECT substr(t, 9) FROM unnest(p.tags) t WHERE t LIKE 'project:%' LIMIT 1) AS project_id
    FROM holdings h
    JOIN portfolios p ON p.portfolio_id = h.portfolio_id AND h.kind = 'portfolio'
    LEFT JOIN securities s ON s.security_id = h.security_id
    LEFT JOIN legacy_companies c ON c.company_id = s.company_id
"""

_VIEWS = {
    # Latest valid snapshot per portfolio, found in one pass (not a per-row
    # subquery). Max over valid dates only, so a malformed as_of_date string
    # cannot win the "latest" comparison.
    "holdings": _HOLDINGS_SELECT
    + """
        JOIN (
            SELECT portfolio_id, max(bi.safe_date(as_of_date)) AS d FROM holdings WHERE kind = 'portfolio'
            GROUP BY portfolio_id
        ) latest ON latest.portfolio_id = h.portfolio_id AND bi.safe_date(h.as_of_date) = latest.d
    """,
    # Every snapshot; junk dates (NULL after the safe cast) are left out.
    "holdings_history": _HOLDINGS_SELECT + " WHERE bi.safe_date(h.as_of_date) IS NOT NULL",
    "company_facts": _FACT_SELECT.format(statuses="'approved', 'edited', 'auto_approved', 'auto_accepted'"),
    "company_facts_pending": _FACT_SELECT.format(statuses="'pending_review'"),
    "run_records": """
        SELECT r.run_id::varchar AS run_id, u.run_type::varchar AS run_type, r.company_id::varchar AS company_id,
               CASE WHEN jsonb_typeof(r.result->'needs_review') = 'boolean'
                    THEN (r.result->>'needs_review')::boolean END AS needs_review,
               CASE WHEN jsonb_typeof(r.result->'overall_confidence') = 'number'
                    THEN (r.result->>'overall_confidence')::double precision END AS overall_confidence,
               r.created_at AS generated_at
        FROM run_results r JOIN runs u ON u.run_id = r.run_id
    """,
    "documents": """
        SELECT doc_id::varchar AS doc_id, company_id::varchar AS company_id, doc_type::varchar AS doc_type,
               title::varchar AS title, source_url::varchar AS source_url, first_seen_at, last_seen_at
        FROM documents
    """,
    # Datasets the monthly run publishes into bi_published (arp/bi/published.py), one JSON object per row.
    # `p.row` is qualified because ROW is also an SQL keyword.
    "portfolio_climate_metrics": """
        SELECT p.row->>'portfolio_id' AS portfolio_id,
               bi.safe_date(p.row->>'as_of_date') AS as_of_date,
               (p.row->>'waci')::double precision AS waci,
               (p.row->>'financed_emissions_tco2e')::double precision AS financed_emissions_tco2e,
               (p.row->>'coverage_pct')::double precision AS coverage_pct,
               (p.row->>'uncovered_market_value_eur')::double precision AS uncovered_market_value_eur
        FROM bi_published p WHERE p.dataset = 'portfolio_climate_metrics'
    """,
    "alerts": """
        SELECT p.month AS month, p.row->>'alert_id' AS alert_id, p.row->>'portfolio_id' AS portfolio_id,
               p.row->>'company_id' AS company_id, p.row->>'category' AS category, p.row->>'status' AS status,
               bi.safe_ts(p.row->>'triggered_at') AS triggered_at,
               (p.row->>'observed_value')::double precision AS observed_value,
               (p.row->>'threshold_value')::double precision AS threshold_value,
               p.row->>'rationale' AS rationale
        FROM bi_published p WHERE p.dataset = 'alerts'
    """,
    "triggers": """
        SELECT p.month AS month, p.row->>'trigger_id' AS trigger_id, p.row->>'source' AS source,
               p.row->>'issuer_id' AS issuer_id, p.row->>'type' AS type, p.row->>'theme' AS theme,
               p.row->>'severity' AS severity, p.row->>'status' AS status,
               p.row->>'first_seen_month' AS first_seen_month, (p.row->>'is_new')::boolean AS is_new,
               p.row->>'reason' AS reason
        FROM bi_published p WHERE p.dataset = 'triggers'
    """,
    "company_profile": """
        SELECT p.month AS month, p.row->>'company_id' AS company_id, p.row->>'company_name' AS company_name,
               p.row->>'field_id' AS field_id, p.row->>'field_name' AS field_name,
               CASE WHEN jsonb_typeof(p.row->'value') = 'number' THEN (p.row->>'value')::double precision END AS value,
               p.row->>'unit' AS unit, bi.safe_date(p.row->>'as_of') AS as_of, p.row->>'source' AS source
        FROM bi_published p WHERE p.dataset = 'company_profile'
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
