"""Rows the monthly run publishes for Superset (arp/bi/published.py) and the Postgres table they land in."""

from __future__ import annotations

import asyncio
import os

import pytest

from arp.bi.published import alert_rows, climate_metric_rows, profile_rows, trigger_rows
from arp.portfolio import datapoint_mapping
from arp.portfolio.climate import metrics as climate_metrics
from arp.portfolio.mock_data import generate_demo_dataset
from arp.portfolio.monitoring.evaluator import evaluate_threshold_rules
from arp.schemas.portfolio import AggregationResult
from arp.schemas.portfolio_monitoring import AlertRule
from arp.schemas.triggers import UnifiedTrigger
from arp.storage.portfolio_store import PortfolioStore
from tests.postgres_helpers import reset_postgres_tables

MONTH = "2026-09"
AS_OF = "2026-09-30"


@pytest.fixture
def store(tmp_path):
    s = PortfolioStore(tmp_path / "pf")
    asyncio.run(generate_demo_dataset(s))
    return s


def _ids(store):
    return [p.portfolio_id for p in store.list_portfolios()]


def test_climate_metric_rows_match_waci_and_pcaf_for_demo_data(store):
    rows = climate_metric_rows(store, MONTH, _ids(store))
    assert [r["portfolio_id"] for r in rows] == sorted(_ids(store)) and rows
    securities = {s.security_id: s for s in store.list_securities()}
    companies = {c.company_id: c for c in store.list_companies()}
    for r in rows:
        holdings = store.load_holdings_as_of(AS_OF, [r["portfolio_id"]])
        waci = climate_metrics.compute_waci(store, holdings, securities, companies, as_of=AS_OF, portfolio_filter=[r["portfolio_id"]])
        pcaf = climate_metrics.compute_financed_emissions(store, holdings, securities, as_of=AS_OF, portfolio_filter=[r["portfolio_id"]])
        assert isinstance(waci, AggregationResult)
        assert r["as_of_date"] == AS_OF
        assert r["waci"] == waci.rows[0].weighted_avg_value
        assert r["financed_emissions_tco2e"] == pcaf["financed_emissions_tco2e"]
        assert r["coverage_pct"] == pcaf["coverage_pct"]
        assert r["uncovered_market_value_eur"] == pcaf["uncovered_market_value_eur"]
    assert any(r["waci"] for r in rows)


def test_climate_metric_rows_skip_portfolios_outside_the_universe(store):
    assert climate_metric_rows(store, MONTH, []) == []


def test_alert_rows_include_status_and_portfolio(store):
    store.save_rule(AlertRule(name="ci", rule_type="field_threshold", field_id="climate_carbon_intensity", comparator="gte", threshold_value=0))
    evaluate_threshold_rules(store, as_of=AS_OF)
    rows = alert_rows(store)
    assert rows and all(r["status"] == "open" for r in rows)
    assert {"alert_id", "portfolio_id", "company_id", "category", "status", "triggered_at", "rationale"} <= set(rows[0])


def test_trigger_rows_flatten_unified_triggers():
    t = UnifiedTrigger(trigger_id="t1", source="stewardship", issuer_id="bmw", type="x", theme="Climate", severity="high", reason="r")
    assert trigger_rows([t]) == [
        {"trigger_id": "t1", "source": "stewardship", "issuer_id": "bmw", "type": "x", "theme": "Climate", "severity": "high",
         "reason": "r", "status": "open", "first_seen_month": "", "is_new": False}
    ]


def test_profile_rows_hold_latest_resolved_value_per_company_and_field(store):
    rows = profile_rows(store, MONTH)
    assert rows and {"company_id", "company_name", "field_id", "field_name", "value", "unit", "as_of", "source"} == set(rows[0])
    assert len({(r["company_id"], r["field_id"]) for r in rows}) == len(rows)
    r = rows[0]
    obs = datapoint_mapping.resolve_field_value(store, r["company_id"], r["field_id"], AS_OF)
    assert (r["value"], r["source"]) == (obs.value, obs.source)


def test_file_store_publish_rows_is_a_noop(store):
    assert store.publish_rows("alerts", MONTH, [{"a": 1}]) is None


DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")


@pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set -- opt-in Postgres integration test")
def test_publish_rows_replaces_same_dataset_month_only(tmp_path):
    from sqlalchemy import text

    from arp.storage.postgres import ensure_schema
    from arp.storage.postgres_portfolio_store import PostgresPortfolioStore

    ensure_schema(DSN)
    reset_postgres_tables(DSN)
    pg = PostgresPortfolioStore(DSN, PortfolioStore(tmp_path / "files"))

    def rows():
        with pg._engine.begin() as conn:
            found = conn.execute(text('SELECT dataset, month, "row"->>\'v\' FROM bi_published ORDER BY dataset, month, 3')).all()
        return [tuple(r) for r in found]

    pg.publish_rows("alerts", "2026-08", [{"v": "old-aug"}])
    pg.publish_rows("alerts", "2026-09", [{"v": "old-sep"}])
    pg.publish_rows("triggers", "2026-09", [{"v": "trig"}])
    pg.publish_rows("alerts", "2026-09", [{"v": "new-1"}, {"v": "new-2"}])
    assert rows() == [
        ("alerts", "2026-08", "old-aug"),
        ("alerts", "2026-09", "new-1"),
        ("alerts", "2026-09", "new-2"),
        ("triggers", "2026-09", "trig"),
    ]
    pg.publish_rows("alerts", "2026-09", [])
    assert [r[:2] for r in rows()] == [("alerts", "2026-08"), ("triggers", "2026-09")]
    reset_postgres_tables(DSN)
