from __future__ import annotations

from arp.portfolio import aggregation, datapoint_mapping
from arp.portfolio.climate.schemas import FIELD_CARBON_INTENSITY, FIELD_EVIC, FIELD_SCOPE1, FIELD_SCOPE2
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import AggregationResult, Holding, SecurityRef, TrendPoint
from arp.storage.portfolio_store import PortfolioStore


def _company_ids(securities: dict[str, SecurityRef]) -> list[str]:
    return sorted({s.company_id for s in securities.values() if s.company_id})


def compute_waci(
    store: PortfolioStore,
    holdings: list[Holding],
    securities: dict[str, SecurityRef],
    companies: dict[str, CompanyRef],
    *,
    as_of: str,
    group_by: str = "portfolio_id",
    portfolio_filter: list[str] | None = None,
) -> AggregationResult:
    """Weighted-average carbon intensity: the weighted_avg_datapoint
    aggregation mode (aggregation.py) applied to the carbon-intensity data
    point, resolved via the same source-priority cascade as every other
    field (datapoint_mapping.py) -- no separate WACI-specific computation.
    """
    values = datapoint_mapping.resolve_field_values_for_universe(store, _company_ids(securities), FIELD_CARBON_INTENSITY, as_of)
    return aggregation.aggregate(
        holdings,
        securities,
        companies,
        group_by=group_by,
        metric="weighted_avg_datapoint",
        as_of=as_of,
        portfolio_filter=portfolio_filter,
        data_point_values=values,
        spec_name="Weighted-Average Carbon Intensity",
    )


def compute_waci_trend(
    store: PortfolioStore,
    holdings_by_date: dict[str, list[Holding]],
    securities: dict[str, SecurityRef],
    companies: dict[str, CompanyRef],
    *,
    group_by: str = "portfolio_id",
    portfolio_filter: list[str] | None = None,
) -> list[TrendPoint]:
    company_ids = _company_ids(securities)
    values_by_date = {
        as_of: datapoint_mapping.resolve_field_values_for_universe(store, company_ids, FIELD_CARBON_INTENSITY, as_of)
        for as_of in holdings_by_date
    }
    return aggregation.aggregate_trend(
        holdings_by_date,
        securities,
        companies,
        group_by=group_by,
        metric="weighted_avg_datapoint",
        portfolio_filter=portfolio_filter,
        data_point_values_by_date=values_by_date,
        spec_name="WACI trend",
    )


def compute_financed_emissions(
    store: PortfolioStore,
    holdings: list[Holding],
    securities: dict[str, SecurityRef],
    *,
    as_of: str,
    portfolio_filter: list[str] | None = None,
) -> dict[str, float | int | str]:
    """Attributed Scope 1+2 financed emissions per the PCAF standard: for
    each holding, `(market_value_eur / issuer EVIC) x issuer Scope1+2`,
    summed across holdings. Any holding whose issuer lacks EVIC or Scope
    1/2 data is excluded from the number and reported separately in
    `uncovered_market_value_eur`/`uncovered_holding_count` rather than
    silently treated as zero-emissions.
    """
    portfolio_set = set(portfolio_filter or [])
    company_ids = _company_ids(securities)
    evic = datapoint_mapping.resolve_field_values_for_universe(store, company_ids, FIELD_EVIC, as_of)
    scope1 = datapoint_mapping.resolve_field_values_for_universe(store, company_ids, FIELD_SCOPE1, as_of)
    scope2 = datapoint_mapping.resolve_field_values_for_universe(store, company_ids, FIELD_SCOPE2, as_of)

    financed_tco2e = 0.0
    covered_mv = 0.0
    uncovered_mv = 0.0
    uncovered_count = 0
    for h in holdings:
        if portfolio_set and h.portfolio_id not in portfolio_set:
            continue
        security = securities.get(h.security_id)
        company_id = security.company_id if security else None
        evic_value = evic.get(company_id) if company_id else None
        s1 = scope1.get(company_id) if company_id else None
        s2 = scope2.get(company_id) if company_id else None
        if not company_id or not evic_value or s1 is None or s2 is None:
            uncovered_mv += h.market_value_eur
            uncovered_count += 1
            continue
        attribution_factor = h.market_value_eur / evic_value
        financed_tco2e += attribution_factor * (s1 + s2)
        covered_mv += h.market_value_eur

    total_mv = covered_mv + uncovered_mv
    return {
        "as_of": as_of,
        "financed_emissions_tco2e": round(financed_tco2e, 1),
        "covered_market_value_eur": round(covered_mv, 2),
        "uncovered_market_value_eur": round(uncovered_mv, 2),
        "coverage_pct": round(covered_mv / total_mv, 4) if total_mv else 0.0,
        "uncovered_holding_count": uncovered_count,
    }


def coverage_report(
    store: PortfolioStore, securities: dict[str, SecurityRef], field_id: str, as_of: str | None = None
) -> dict[str, int]:
    """Per-source coverage counts (internal API / extracted / estimated /
    missing) for one climate field, across the full issuer universe --
    always shown alongside a climate number so partial coverage is never
    mistaken for complete data."""
    return datapoint_mapping.coverage_summary(store, _company_ids(securities), field_id, as_of)
