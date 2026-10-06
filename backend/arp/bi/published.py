"""Rows the monthly run publishes for Superset (see PortfolioStore.publish_rows and the `bi` views over `bi_published`).
The formulas stay in Python: this only calls climate/metrics.py and aggregation.py and flattens the results."""

from __future__ import annotations

import calendar
from datetime import datetime

from arp.portfolio import datapoint_mapping
from arp.portfolio.climate import metrics
from arp.portfolio.monitoring.evaluator import list_alerts
from arp.schemas.triggers import UnifiedTrigger
from arp.storage.portfolio_store import PortfolioStore, portfolio_directories


def month_end(month: str) -> str:
    first = datetime.strptime(month, "%Y-%m")  # ValueError if malformed
    return f"{month}-{calendar.monthrange(first.year, first.month)[1]:02d}"


def climate_metric_rows(store: PortfolioStore, month: str, portfolio_ids: list[str], obs_as_of: str | None = None) -> list[dict]:
    """Holdings as of the month end; observations as of `obs_as_of` (default the month end)."""
    as_of = month_end(month)
    obs_as_of = obs_as_of or as_of
    securities, companies = portfolio_directories(store)
    rows = []
    for pid in sorted(portfolio_ids):
        holdings = store.load_holdings_as_of(as_of, [pid])
        if not holdings:
            continue
        waci = metrics.compute_waci(store, holdings, securities, companies, as_of=obs_as_of, portfolio_filter=[pid])
        pcaf = metrics.compute_financed_emissions(store, holdings, securities, as_of=obs_as_of, portfolio_filter=[pid])
        rows.append(
            {
                "portfolio_id": pid,
                "as_of_date": as_of,
                "waci": waci.rows[0].weighted_avg_value if waci.rows else None,
                "financed_emissions_tco2e": pcaf["financed_emissions_tco2e"],
                "coverage_pct": pcaf["coverage_pct"],
                "uncovered_market_value_eur": pcaf["uncovered_market_value_eur"],
            }
        )
    return rows


def alert_rows(store: PortfolioStore) -> list[dict]:
    return [
        {
            "alert_id": a.alert_id,
            "portfolio_id": a.portfolio_id,
            "company_id": a.company_id,
            "category": a.category.value,
            "status": a.status.value,
            "triggered_at": a.triggered_at,
            "observed_value": a.observed_value,
            "threshold_value": a.threshold_value,
            "rationale": a.rationale,
        }
        for a in list_alerts(store)
    ]


def trigger_rows(triggers: list[UnifiedTrigger]) -> list[dict]:
    return [t.model_dump() for t in triggers]


def profile_rows(store: PortfolioStore, month: str, obs_as_of: str | None = None) -> list[dict]:
    """Latest resolved observation per company and field as of `obs_as_of` (default the month end), by source priority."""
    as_of = obs_as_of or month_end(month)
    names = {c.company_id: c.name for c in store.list_companies()}
    rows = []
    for company_id, field_id in sorted(store.list_observation_keys()):
        obs = datapoint_mapping.resolve_field_value(store, company_id, field_id, as_of)
        if obs is None:
            continue
        rows.append(
            {
                "company_id": company_id,
                "company_name": names.get(company_id, company_id),
                "field_id": field_id,
                "field_name": obs.field_name,
                "value": obs.value,
                "unit": obs.unit,
                "as_of": obs.observed_at[:10],
                "source": obs.source,
            }
        )
    return rows
