from __future__ import annotations

from collections import defaultdict

from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import AggregationRow, AggregationResult, Holding, SecurityRef, TrendPoint

DIMENSIONS = ("portfolio_id", "asset_class", "company_id", "company_name", "sector", "country", "currency")
"""Built-in grouping/filter dimensions. Each is a pure lookup on the joined
holding + security + company row -- no LLM, no I/O. `company_id`/`company_name`/
`sector`/`country` all resolve through `SecurityRef.company_id`, so a
security that hasn't been through entity resolution yet groups into
"(unresolved)" rather than silently disappearing from a query.
"""


def _dimension_value(holding: Holding, securities: dict[str, SecurityRef], companies: dict[str, CompanyRef], dimension: str) -> str | None:
    if dimension not in DIMENSIONS:
        raise ValueError(f"Unknown aggregation dimension: {dimension!r}. Valid: {DIMENSIONS}")
    if dimension == "portfolio_id":
        return holding.portfolio_id
    security = securities.get(holding.security_id)
    if dimension == "asset_class":
        return security.asset_class if security else None
    if dimension == "currency":
        return security.currency if security else None
    if dimension == "company_id":
        return security.company_id if security else None
    company = companies.get(security.company_id) if security and security.company_id else None
    if dimension == "company_name":
        return company.name if company else (security.name if security else None)
    if dimension == "sector":
        return company.sector if company else None
    if dimension == "country":
        return company.country if company else None
    return None  # pragma: no cover -- unreachable, DIMENSIONS is exhaustive above


def _passes_filter(
    holding: Holding,
    securities: dict[str, SecurityRef],
    companies: dict[str, CompanyRef],
    security_filter: dict[str, str],
    portfolio_filter: list[str],
) -> bool:
    if portfolio_filter and holding.portfolio_id not in portfolio_filter:
        return False
    for key, value in security_filter.items():
        if _dimension_value(holding, securities, companies, key) != value:
            return False
    return True


def aggregate(
    holdings: list[Holding],
    securities: dict[str, SecurityRef],
    companies: dict[str, CompanyRef],
    *,
    group_by: str,
    metric: str,
    as_of: str,
    security_filter: dict[str, str] | None = None,
    portfolio_filter: list[str] | None = None,
    data_point_values: dict[str, float] | None = None,
    spec_name: str = "",
) -> AggregationResult:
    """The core, deterministic (zero-LLM) aggregation primitive. Given a set
    of holdings and a grouping dimension, produces either grouped
    market-value sums, a plain count, or a value-weighted average of a
    data point -- the three modes every portfolio query in this system
    reduces to.

    `data_point_values` is `{company_id: value}` for exactly the field
    being aggregated, pre-resolved by `datapoint_mapping.py` -- this
    function never resolves or infers a value itself. A holding whose
    issuer has no value for that field is excluded from the weighted
    average (not treated as zero) and its market value is reported
    separately in `unresolved_market_value_eur`, so a caller can never
    mistake partial coverage for a complete answer.
    """
    security_filter = security_filter or {}
    portfolio_filter = portfolio_filter or []
    data_point_values = data_point_values or {}

    if metric == "weighted_avg_datapoint" and not data_point_values:
        raise ValueError("metric='weighted_avg_datapoint' requires data_point_values")

    filtered = [h for h in holdings if _passes_filter(h, securities, companies, security_filter, portfolio_filter)]

    groups: dict[str, list[Holding]] = defaultdict(list)
    for h in filtered:
        key = _dimension_value(h, securities, companies, group_by) or "(unresolved)"
        groups[key].append(h)

    rows: list[AggregationRow] = []
    unresolved_mv_total = 0.0
    for key in sorted(groups):
        hs = groups[key]
        mv_total = sum(h.market_value_eur for h in hs)

        if metric == "market_value_sum":
            rows.append(AggregationRow(group_value=key, market_value_eur=round(mv_total, 2), holding_count=len(hs)))
        elif metric == "count":
            rows.append(AggregationRow(group_value=key, holding_count=len(hs)))
        elif metric == "weighted_avg_datapoint":
            weighted_sum = 0.0
            covered_mv = 0.0
            for h in hs:
                security = securities.get(h.security_id)
                company_id = security.company_id if security else None
                value = data_point_values.get(company_id) if company_id else None
                if value is None:
                    unresolved_mv_total += h.market_value_eur
                    continue
                weighted_sum += h.market_value_eur * value
                covered_mv += h.market_value_eur
            avg = weighted_sum / covered_mv if covered_mv else None
            coverage = covered_mv / mv_total if mv_total else 0.0
            rows.append(
                AggregationRow(
                    group_value=key,
                    market_value_eur=round(mv_total, 2),
                    weighted_avg_value=round(avg, 4) if avg is not None else None,
                    coverage_pct=round(coverage, 4),
                    holding_count=len(hs),
                )
            )
        else:
            raise ValueError(f"Unknown aggregation metric: {metric!r}")

    return AggregationResult(
        spec_name=spec_name,
        as_of=as_of,
        metric=metric,
        group_by=group_by,
        rows=rows,
        total_market_value_eur=round(sum(h.market_value_eur for h in filtered), 2),
        unresolved_market_value_eur=round(unresolved_mv_total, 2),
    )


def aggregate_trend(
    holdings_by_date: dict[str, list[Holding]],
    securities: dict[str, SecurityRef],
    companies: dict[str, CompanyRef],
    *,
    group_by: str,
    metric: str,
    security_filter: dict[str, str] | None = None,
    portfolio_filter: list[str] | None = None,
    data_point_values_by_date: dict[str, dict[str, float]] | None = None,
    spec_name: str = "",
) -> list[TrendPoint]:
    """Runs `aggregate` once per snapshot date, for the "how has this moved
    over time" queries decision 5 requires -- same engine, no separate
    code path, so a trend line and a point-in-time answer can never
    disagree about how a number is computed.
    """
    data_point_values_by_date = data_point_values_by_date or {}
    points: list[TrendPoint] = []
    for as_of in sorted(holdings_by_date):
        result = aggregate(
            holdings_by_date[as_of],
            securities,
            companies,
            group_by=group_by,
            metric=metric,
            as_of=as_of,
            security_filter=security_filter,
            portfolio_filter=portfolio_filter,
            data_point_values=data_point_values_by_date.get(as_of),
            spec_name=spec_name,
        )
        points.append(TrendPoint(as_of=as_of, result=result))
    return points
