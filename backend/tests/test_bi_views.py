"""The `bi` schema: the only thing the BI tool's read-only role may see.
Skipped without ARP_TEST_POSTGRES_DSN, like every other Postgres suite."""

from __future__ import annotations

import os

import pytest

from arp.bi.catalog import VIEW_DATASETS
from arp.storage.postgres_schema import ensure_schema
from tests.postgres_helpers import reset_postgres_tables

DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set -- opt-in Postgres backend")

_PASSWORD = "bi-test-password"
# Roles are cluster-wide: the tests use their own so a developer's real bi_reader is never touched.
_ROLE = "bi_reader_test"


@pytest.fixture
def engine():
    from sqlalchemy import text

    from arp.bi.views import create_bi_views, ensure_reader_role
    from arp.storage.postgres import get_engine

    ensure_schema(DSN)
    reset_postgres_tables(DSN)
    eng = get_engine(DSN)
    with eng.begin() as conn:
        create_bi_views(conn)  # pick up view edits on a DB that already recorded step 0002
        ensure_reader_role(conn, _PASSWORD, role=_ROLE)
    yield eng
    reset_postgres_tables(DSN)
    with eng.begin() as conn:
        conn.execute(text(f"DROP OWNED BY {_ROLE}"))
        conn.execute(text(f"DROP ROLE {_ROLE}"))


def _q(engine, sql):
    from sqlalchemy import text

    with engine.begin() as conn:
        return conn.execute(text(sql)).all()


def _seed(engine, facts=(), holdings_date="2026-02-28"):
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("INSERT INTO portfolios (portfolio_id, name, tags) VALUES ('p1', 'Core', '{}')"))
        conn.execute(text("INSERT INTO legacy_companies (company_id, name, sector, country) VALUES ('bmw', 'BMW', 'Auto', 'DE')"))
        conn.execute(
            text(
                "INSERT INTO securities (security_id, name, asset_class, currency, company_id) VALUES ('s1', 'BMW', 'equity', 'EUR', 'bmw')"
            )
        )
        for d, mv in (("2026-01-31", 5.0), (holdings_date, 100.0)):
            conn.execute(
                text(
                    "INSERT INTO holdings (portfolio_id, security_id, as_of_date, quantity, price, market_value,"
                    " fx_rate_to_eur, market_value_eur, weight_pct) VALUES ('p1', 's1', :d, 1, :mv, :mv, 1, :mv, 100)"
                ),
                {"d": d, "mv": mv},
            )
    if facts:
        _seed_facts(engine, facts)


def _seed_facts(engine, facts):
    """(field_id, period_end or None, status, JSON value, current) rows in `company_facts` for one company."""
    import json
    from datetime import UTC, date, datetime

    from sqlalchemy.orm import Session

    from arp.db import models as m

    with Session(engine) as s, s.begin():
        c = m.Company(name="BMW")
        s.add(c)
        s.flush()
        for key, as_of, status, value, current in facts:
            s.add(m.Field(field_id=key, kind=m.FieldKind.EXTRACTED))
            s.flush()
            s.add(m.FieldDefinition(field_id=key, version=1, name=key, data_type="number", definition={}))
            s.flush()
            v = json.loads(value)
            obs = m.FieldObservation(company_id=c.id, field_id=key, field_version=1, source_kind=m.SourceKind.MANUAL,
                                     value=v, value_state=m.ValueState.FOUND, confidence=0.9)
            s.add(obs)
            s.flush()
            s.add(m.CompanyFact(
                company_id=c.id, field_id=key, period_end=date.fromisoformat(as_of) if as_of else None, value=v,
                status=status, observation_id=obs.id, valid_to=None if current else datetime.now(UTC),
            ))


def test_views_match_catalog_columns(engine):
    for name, dataset in VIEW_DATASETS.items():
        cols = [
            r[0]
            for r in _q(
                engine,
                f"SELECT column_name FROM information_schema.columns WHERE table_schema='bi' AND table_name='{name}' ORDER BY ordinal_position",
            )
        ]
        assert cols == list(dataset.columns), name


def test_published_views_cast_bi_published_rows_by_dataset(engine):
    import json

    from sqlalchemy import text

    rows = {
        "portfolio_climate_metrics": {"portfolio_id": "p1", "as_of_date": "2026-09-30", "waci": 12.5, "financed_emissions_tco2e": 3.0,
                                      "coverage_pct": 0.5, "uncovered_market_value_eur": 7.0},
        "alerts": {"alert_id": "a1", "portfolio_id": "p1", "status": "open", "triggered_at": "2026-09-30T00:00:00+00:00"},
        "triggers": {"trigger_id": "t1", "status": "open", "is_new": True},
        "company_profile": {"company_id": "bmw", "field_id": "f", "value": 4.5, "as_of": "2026-09-01"},
    }
    with engine.begin() as conn:
        for dataset, row in rows.items():
            conn.execute(
                text("INSERT INTO bi_published (dataset, month, row) VALUES (:d, '2026-09', CAST(:r AS jsonb))"),
                {"d": dataset, "r": json.dumps(row)},
            )
    assert tuple(_q(engine, "SELECT waci, as_of_date::text FROM bi.portfolio_climate_metrics")[0]) == (12.5, "2026-09-30")
    assert tuple(_q(engine, "SELECT status, portfolio_id, month FROM bi.alerts")[0]) == ("open", "p1", "2026-09")
    assert tuple(_q(engine, "SELECT trigger_id, is_new FROM bi.triggers")[0]) == ("t1", True)
    assert tuple(_q(engine, "SELECT value, as_of::text FROM bi.company_profile")[0]) == (4.5, "2026-09-01")


def test_holdings_view_matches_base_tables_total(engine):
    _seed(engine)
    # latest snapshot only (the January row is excluded)
    assert _q(engine, "SELECT sum(market_value_eur) FROM bi.holdings")[0][0] == 100.0
    assert _q(engine, "SELECT sum(market_value_eur) FROM holdings WHERE as_of_date = '2026-02-28'")[0][0] == 100.0
    row = _q(engine, "SELECT portfolio_name, company_name, sector FROM bi.holdings")[0]
    assert tuple(row) == ("Core", "BMW", "Auto")


def test_holdings_view_keeps_each_portfolios_own_latest_snapshot(engine):
    from sqlalchemy import text

    _seed(engine)  # p1: 2026-01-31 and 2026-02-28
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO portfolios (portfolio_id, name, tags) VALUES ('p2', 'Older', '{}')"))
        for d, mv in (("2025-12-31", 7.0), ("2026-01-31", 9.0)):
            conn.execute(
                text(
                    "INSERT INTO holdings (portfolio_id, security_id, as_of_date, quantity, price, market_value,"
                    " fx_rate_to_eur, market_value_eur, weight_pct) VALUES ('p2', 's1', :d, 1, :mv, :mv, 1, :mv, 100)"
                ),
                {"d": d, "mv": mv},
            )
    rows = _q(engine, "SELECT portfolio_id, as_of_date::text, market_value_eur FROM bi.holdings ORDER BY portfolio_id")
    assert [tuple(r) for r in rows] == [("p1", "2026-02-28", 100.0), ("p2", "2026-01-31", 9.0)]


def test_as_of_date_is_a_date(engine):
    _seed(engine)
    assert _q(engine, "SELECT pg_typeof(as_of_date)::text FROM bi.holdings")[0][0] == "date"


def test_facts_view_excludes_pending_and_rejected(engine):
    _seed(
        engine,
        facts=[
            ("a", "", "approved", "1", True),
            ("b", "", "pending_review", "2", True),
            ("c", "", "held", "3", True),
            ("d", "", "auto_accepted", "4", True),
            ("e", "", "edited", "5", True),
            ("f", "", "approved", "6", False),
        ],
    )
    assert sorted(r[0] for r in _q(engine, "SELECT fact_key FROM bi.company_facts")) == ["a", "d", "e"]


def test_pending_view_holds_only_pending(engine):
    _seed(
        engine,
        facts=[
            ("a", "", "approved", "1", True),
            ("b", "", "pending_review", "2", True),
            ("c", "", "pending_review", "3", False),
        ],
    )
    assert [r[0] for r in _q(engine, "SELECT fact_key FROM bi.company_facts_pending")] == ["b"]


def test_value_num_null_when_no_numeric(engine):
    _seed(
        engine,
        facts=[
            ("num", "", "approved", "12.5", True),
            ("txt", "", "approved", '"hello"', True),
            ("none", "", "approved", '{"company_id": "bmw"}', True),
            ("nul", "", "approved", "null", True),
            ("huge", "", "approved", "1e308", True),
        ],
    )
    rows = {r[0]: (r[1], r[2]) for r in _q(engine, "SELECT fact_key, value_num, value_text FROM bi.company_facts")}
    assert rows["num"] == (12.5, None)
    assert rows["txt"] == (None, "hello")
    assert rows["none"] == (None, None)
    assert rows["nul"] == (None, None)
    assert rows["huge"] == (None, None)  # beyond the 1e300 guard: NULL, not an error


def test_fact_as_of_is_the_period_end_date(engine):
    _seed(engine, facts=[("none", "", "approved", "1", True), ("ok", "2026-03-31", "approved", "1", True)])
    rows = {r[0]: r[1] for r in _q(engine, "SELECT fact_key, as_of FROM bi.company_facts")}
    assert rows["none"] is None and str(rows["ok"]) == "2026-03-31"
    assert _q(engine, "SELECT pg_typeof(as_of)::text FROM bi.company_facts LIMIT 1")[0][0] == "date"


def test_malformed_holdings_date_does_not_break_view(engine):
    _seed(engine, holdings_date="garbage")
    assert _q(engine, "SELECT as_of_date FROM bi.holdings")[0][0] is not None  # Jan snapshot wins


def test_bi_reader_cannot_select_base_tables(engine):
    import sqlalchemy as sa
    from sqlalchemy.exc import ProgrammingError

    _seed(engine)
    url = sa.engine.make_url(DSN).set(username=_ROLE, password=_PASSWORD)
    reader = sa.create_engine(url)
    try:
        with reader.connect() as conn:
            assert conn.execute(sa.text("SELECT count(*) FROM bi.holdings")).scalar() == 1
        for table in ("holdings", "public.company_facts"):
            with reader.connect() as conn, pytest.raises(ProgrammingError, match="permission denied"):
                conn.execute(sa.text(f"SELECT * FROM {table}"))
    finally:
        reader.dispose()


def test_ensure_reader_role_is_idempotent(engine):
    from arp.bi.views import create_bi_views, ensure_reader_role

    with engine.begin() as conn:
        create_bi_views(conn)
        ensure_reader_role(conn, _PASSWORD, role=_ROLE)
        ensure_reader_role(conn, _PASSWORD, role=_ROLE)


def test_run_records_excludes_payload(engine):
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("INSERT INTO runs (run_id, run_type, status) VALUES ('r1', 'extraction', 'completed')"))
        conn.execute(text(
            "INSERT INTO run_results (run_id, result_key, result) VALUES"
            " ('r1', 'bmw', '{\"needs_review\": false, \"overall_confidence\": 0.9, \"secret\": 1}')"
        ))
    cols = [
        r[0]
        for r in _q(
            engine, "SELECT column_name FROM information_schema.columns WHERE table_schema='bi' AND table_name='run_records'"
        )
    ]
    assert "payload" not in cols and "result" not in cols
    assert tuple(_q(engine, "SELECT run_type, needs_review, overall_confidence FROM bi.run_records")[0]) == (
        "extraction", False, 0.9)
    assert _q(engine, "SELECT pg_typeof(generated_at)::text FROM bi.run_records")[0][0] == "timestamp with time zone"


def test_documents_view_reads_the_registry(engine):
    from sqlalchemy.orm import Session

    from arp.db import models as m

    with Session(engine) as s, s.begin():
        c = m.Company(name="BMW")
        s.add(c)
        s.flush()
        s.add(m.Document(doc_id="d1", company_id=c.id, doc_type="10-K", title="AR", content_key="ck"))
        cid = str(c.id)
    assert [tuple(r) for r in _q(engine, "SELECT doc_id, company_id, title FROM bi.documents")] == [("d1", cid, "AR")]


def test_reader_password_with_colon_and_quote(engine):
    import sqlalchemy as sa

    from arp.bi.views import ensure_reader_role

    pw = "pw!:abc x'y"
    _seed(engine)
    with engine.begin() as conn:
        ensure_reader_role(conn, pw, role=_ROLE)
    reader = sa.create_engine(sa.engine.make_url(DSN).set(username=_ROLE, password=pw))
    try:
        with reader.connect() as conn:
            assert conn.execute(sa.text("SELECT count(*) FROM bi.holdings")).scalar() == 1
    finally:
        reader.dispose()


def test_holdings_history_has_every_snapshot(engine):
    _seed(engine)  # 2026-01-31 and 2026-02-28 for p1
    rows = _q(engine, "SELECT as_of_date::text FROM bi.holdings_history ORDER BY as_of_date")
    assert [r[0] for r in rows] == ["2026-01-31", "2026-02-28"]
    assert [r[0] for r in _q(engine, "SELECT as_of_date::text FROM bi.holdings")] == ["2026-02-28"]


def test_holdings_history_excludes_junk_dates_and_empty_table_is_ok(engine):
    from sqlalchemy import text

    _seed(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO holdings (portfolio_id, security_id, as_of_date, quantity, price, market_value,"
                " fx_rate_to_eur, market_value_eur, weight_pct) VALUES ('p1', 's1', 'junk', 1, 1, 1, 1, 1, 1)"
            )
        )
    assert [r[0] for r in _q(engine, "SELECT as_of_date::text FROM bi.holdings_history ORDER BY 1")] == [
        "2026-01-31",
        "2026-02-28",
    ]
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM holdings"))
    assert _q(engine, "SELECT count(*) FROM bi.holdings_history")[0][0] == 0


def test_history_columns_match_catalog(engine):
    cols = [
        r[0]
        for r in _q(
            engine,
            "SELECT column_name FROM information_schema.columns WHERE table_schema='bi'"
            " AND table_name='holdings_history' ORDER BY ordinal_position",
        )
    ]
    assert cols == list(VIEW_DATASETS["holdings_history"].columns)


def test_project_id_is_the_project_tag_suffix_or_null(engine):
    from sqlalchemy import text

    _seed(engine)
    with engine.begin() as conn:
        conn.execute(text("UPDATE portfolios SET tags = '{project:alpha}' WHERE portfolio_id = 'p1'"))
        conn.execute(text("INSERT INTO portfolios (portfolio_id, name, tags) VALUES ('p-b', 'B', '{x,project:beta}')"))
        conn.execute(text("INSERT INTO portfolios (portfolio_id, name, tags) VALUES ('p-c', 'C', '{x}')"))
        for pid in ("p-b", "p-c"):
            conn.execute(
                text(
                    "INSERT INTO holdings (portfolio_id, security_id, as_of_date, quantity, price, market_value,"
                    " fx_rate_to_eur, market_value_eur, weight_pct) VALUES (:p, 's1', '2026-02-28', 1, 1, 1, 1, 1, 100)"
                ),
                {"p": pid},
            )
    for view in ("holdings", "holdings_history"):
        rows = _q(engine, f"SELECT DISTINCT portfolio_id, project_id FROM bi.{view}")
        # sorted in Python: SQL ORDER BY follows the database collation ("p1" vs "p-b" differ by locale)
        assert sorted(tuple(r) for r in rows) == [("p-b", "beta"), ("p-c", None), ("p1", "alpha")], view
