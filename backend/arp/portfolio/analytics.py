from __future__ import annotations

import json

from arp.portfolio import aggregation, datapoint_mapping
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import AggregationResult, AnalyticSpec, SecurityRef, TrendPoint
from arp.storage.portfolio_store import PortfolioStore


def save_analytic(store: PortfolioStore, spec: AnalyticSpec) -> None:
    store.save_analytic(json.loads(spec.model_dump_json()))


def list_analytics(store: PortfolioStore) -> list[AnalyticSpec]:
    return [AnalyticSpec.model_validate(row) for row in store.list_analytics()]


def get_analytic(store: PortfolioStore, analytic_id: str) -> AnalyticSpec | None:
    row = store.get_analytic(analytic_id)
    return AnalyticSpec.model_validate(row) if row else None


def execute(
    spec: AnalyticSpec,
    store: PortfolioStore,
    securities: dict[str, SecurityRef],
    companies: dict[str, CompanyRef],
) -> AggregationResult | list[TrendPoint]:
    """Executes a saved/drafted AnalyticSpec against current holdings data
    -- the only place a portfolio number actually gets computed. Whether
    the spec came from the Analytics Builder UI or `qa_agent.py`'s NL
    parsing makes no difference here; both paths converge on this one
    deterministic executor, so the same question always gets the same
    answer regardless of how it was asked.
    """
    company_ids = sorted({s.company_id for s in securities.values() if s.company_id})

    if spec.date_range:
        start, end = spec.date_range
        dates = [d for d in store.all_snapshot_dates() if start <= d <= end]
        holdings_by_date = {d: store.load_holdings_as_of(d, spec.portfolio_filter or None) for d in dates}
        values_by_date = None
        if spec.metric == "weighted_avg_datapoint":
            if not spec.data_point_field_id:
                raise ValueError("metric='weighted_avg_datapoint' requires data_point_field_id")
            values_by_date = {
                d: datapoint_mapping.resolve_field_values_for_universe(store, company_ids, spec.data_point_field_id, d)
                for d in dates
            }
        return aggregation.aggregate_trend(
            holdings_by_date,
            securities,
            companies,
            group_by=spec.group_by,
            metric=spec.metric,
            security_filter=spec.security_filter,
            portfolio_filter=spec.portfolio_filter or None,
            data_point_values_by_date=values_by_date,
            spec_name=spec.name,
        )

    if spec.as_of:
        as_of = spec.as_of
    else:
        available_dates = store.all_snapshot_dates()
        as_of = available_dates[-1] if available_dates else None
    if as_of is None:
        raise ValueError("No holdings snapshots available")

    holdings = store.load_holdings_as_of(as_of, spec.portfolio_filter or None)
    values = None
    if spec.metric == "weighted_avg_datapoint":
        if not spec.data_point_field_id:
            raise ValueError("metric='weighted_avg_datapoint' requires data_point_field_id")
        values = datapoint_mapping.resolve_field_values_for_universe(store, company_ids, spec.data_point_field_id, as_of)

    return aggregation.aggregate(
        holdings,
        securities,
        companies,
        group_by=spec.group_by,
        metric=spec.metric,
        as_of=as_of,
        security_filter=spec.security_filter,
        portfolio_filter=spec.portfolio_filter or None,
        data_point_values=values,
        spec_name=spec.name,
    )
