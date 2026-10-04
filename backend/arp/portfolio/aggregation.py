from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from arp.config import get_settings
from arp.research.standards_mapping.gics import load_company_gics, load_gics_reference
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import AggregationResult, AggregationRow, Holding, PivotCell, PivotResult, SecurityRef, TrendPoint

_GICS_LEVELS = {"gics_sector": 2, "gics_industry_group": 4, "gics_industry": 6, "gics_sub_industry": 8}
DIMENSIONS = ("portfolio_id", "asset_class", "company_id", "company_name", "sector", "country", "currency", *_GICS_LEVELS)
"""Built-in grouping/filter dimensions. Each is a pure lookup on the joined
holding + security + company row -- no LLM, no I/O. `company_id`/`company_name`/
`sector`/`country` all resolve through `SecurityRef.company_id`, so a
security that hasn't been through entity resolution yet groups into
"(unresolved)" rather than silently disappearing from a query.
"""

_VALID_METRICS = ("market_value_sum", "weighted_avg_datapoint", "count")


@lru_cache
def _gics_tables(reference_path: Path | None, company_path: Path | None) -> tuple[dict[str, str], dict[str, str]]:
    """(code -> label, company_id -> code); empty when a file is unset or missing."""
    labels = {e.code: e.label for e in load_gics_reference(reference_path)} if reference_path and reference_path.exists() else {}
    codes = load_company_gics(company_path) if company_path and company_path.exists() else {}
    return labels, codes


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
    if dimension in _GICS_LEVELS:
        settings = get_settings()
        labels, codes = _gics_tables(settings.gics_reference_path, settings.company_gics_path)
        code = codes.get(security.company_id) if security and security.company_id else None
        return labels.get(code[: _GICS_LEVELS[dimension]]) if code else None
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
    return all(_dimension_value(holding, securities, companies, key) == value for key, value in security_filter.items())


def _group_metric(
    hs: list[Holding], metric: str, securities: dict[str, SecurityRef], data_point_values: dict[str, float]
) -> tuple[float, float | None, float | None, float, int]:
    """The per-group/per-cell metric computation shared by `aggregate` and
    `pivot`, so a single-dimension result and a two-dimension permutation of
    the same query can never silently disagree about how a number is
    computed. Returns (market_value_eur, weighted_avg_value, coverage_pct,
    unresolved_market_value_eur, holding_count).
    """
    mv_total = round(sum(h.market_value_eur for h in hs), 2)
    count = len(hs)
    if metric != "weighted_avg_datapoint":
        return mv_total, None, None, 0.0, count

    weighted_sum = 0.0
    covered_mv = 0.0
    unresolved_mv = 0.0
    for h in hs:
        security = securities.get(h.security_id)
        company_id = security.company_id if security else None
        value = data_point_values.get(company_id) if company_id else None
        if value is None:
            unresolved_mv += h.market_value_eur
            continue
        weighted_sum += h.market_value_eur * value
        covered_mv += h.market_value_eur
    avg = weighted_sum / covered_mv if covered_mv else None
    coverage = covered_mv / mv_total if mv_total else 0.0
    return mv_total, (round(avg, 4) if avg is not None else None), round(coverage, 4), round(unresolved_mv, 2), count


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
    if metric not in _VALID_METRICS:
        raise ValueError(f"Unknown aggregation metric: {metric!r}. Valid: {_VALID_METRICS}")
    security_filter = security_filter or {}
    portfolio_filter = portfolio_filter or []
    # None = caller forgot the values; {} = resolved but nothing covered (valid, all unresolved)
    if metric == "weighted_avg_datapoint" and data_point_values is None:
        raise ValueError("metric='weighted_avg_datapoint' requires data_point_values")
    data_point_values = data_point_values or {}

    filtered = [h for h in holdings if _passes_filter(h, securities, companies, security_filter, portfolio_filter)]

    groups: dict[str, list[Holding]] = defaultdict(list)
    for h in filtered:
        key = _dimension_value(h, securities, companies, group_by) or "(unresolved)"
        groups[key].append(h)

    rows: list[AggregationRow] = []
    unresolved_mv_total = 0.0
    for key in sorted(groups):
        mv_total, avg, coverage, unresolved_mv, count = _group_metric(groups[key], metric, securities, data_point_values)
        unresolved_mv_total += unresolved_mv
        rows.append(
            AggregationRow(
                group_value=key,
                market_value_eur=mv_total if metric != "count" else None,
                weighted_avg_value=avg,
                coverage_pct=coverage,
                holding_count=count,
            )
        )

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


def pivot(
    holdings: list[Holding],
    securities: dict[str, SecurityRef],
    companies: dict[str, CompanyRef],
    *,
    row_dim: str,
    col_dim: str,
    metric: str,
    as_of: str,
    security_filter: dict[str, str] | None = None,
    portfolio_filter: list[str] | None = None,
    data_point_values: dict[str, float] | None = None,
    spec_name: str = "",
) -> PivotResult:
    """A two-dimension permutation of `aggregate` -- e.g. sector x asset
    class, or issuer x portfolio to see one exposure figure broken out
    across every portfolio at once in a single query. Uses the exact same
    per-cell metric computation as `aggregate` (`_group_metric`), so a 1D
    result and a 2D cross-tab of the same underlying query can never
    silently disagree. A (row, col) combination with no matching holdings
    is simply absent from `cells` -- never fabricated as a zero cell.
    """
    if metric not in _VALID_METRICS:
        raise ValueError(f"Unknown aggregation metric: {metric!r}. Valid: {_VALID_METRICS}")
    security_filter = security_filter or {}
    portfolio_filter = portfolio_filter or []
    # None = caller forgot the values; {} = resolved but nothing covered (valid, all unresolved)
    if metric == "weighted_avg_datapoint" and data_point_values is None:
        raise ValueError("metric='weighted_avg_datapoint' requires data_point_values")
    data_point_values = data_point_values or {}

    filtered = [h for h in holdings if _passes_filter(h, securities, companies, security_filter, portfolio_filter)]

    groups: dict[tuple[str, str], list[Holding]] = defaultdict(list)
    for h in filtered:
        row_key = _dimension_value(h, securities, companies, row_dim) or "(unresolved)"
        col_key = _dimension_value(h, securities, companies, col_dim) or "(unresolved)"
        groups[(row_key, col_key)].append(h)

    cells: list[PivotCell] = []
    unresolved_mv_total = 0.0
    for row_key, col_key in sorted(groups):
        mv_total, avg, coverage, unresolved_mv, count = _group_metric(groups[(row_key, col_key)], metric, securities, data_point_values)
        unresolved_mv_total += unresolved_mv
        cells.append(
            PivotCell(
                row_value=row_key,
                col_value=col_key,
                market_value_eur=mv_total if metric != "count" else None,
                weighted_avg_value=avg,
                coverage_pct=coverage,
                holding_count=count,
            )
        )

    return PivotResult(
        spec_name=spec_name,
        as_of=as_of,
        metric=metric,
        row_dim=row_dim,
        col_dim=col_dim,
        row_values=sorted({c.row_value for c in cells}),
        col_values=sorted({c.col_value for c in cells}),
        cells=cells,
        total_market_value_eur=round(sum(h.market_value_eur for h in filtered), 2),
        unresolved_market_value_eur=round(unresolved_mv_total, 2),
    )
