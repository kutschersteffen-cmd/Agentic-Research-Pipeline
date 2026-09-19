from __future__ import annotations

from arp.portfolio import analytics
from arp.portfolio.climate.schemas import build_climate_schema
from arp.portfolio.genbi import observations
from arp.portfolio.genbi.schemas import PanelResult, PanelSpec
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import AggregationResult, AnalyticSpec, PivotSpec, SecurityRef
from arp.storage.portfolio_store import PortfolioStore


def _field_unit(field_id: str | None) -> str:
    if not field_id:
        return ""
    field = next((f for f in build_climate_schema().fields if f.field_id == field_id), None)
    return field.unit or "" if field else ""


def execute_panel(
    panel: PanelSpec,
    store: PortfolioStore,
    securities: dict[str, SecurityRef],
    companies: dict[str, CompanyRef],
) -> PanelResult:
    """Runs one planned panel through the same deterministic engine the
    Explore and Pivot tabs use -- `analytics.execute` / `execute_pivot`, no
    generative-BI-specific computation anywhere -- and attaches the facts
    derived from the result.

    A panel that fails (unknown field, no snapshots in range) returns a
    PanelResult carrying `error` instead of raising: one unexecutable panel
    reports itself as failed on the dashboard, it does not take the other
    panels down with it.
    """
    unit = _field_unit(panel.data_point_field_id)
    try:
        if panel.kind == "pivot":
            pivot = analytics.execute_pivot(
                PivotSpec(
                    name=panel.title,
                    portfolio_filter=panel.portfolio_filter,
                    security_filter=panel.security_filter,
                    row_dim=panel.row_dim,
                    col_dim=panel.col_dim,
                    metric=panel.metric,
                    data_point_field_id=panel.data_point_field_id,
                    as_of=panel.as_of,
                ),
                store,
                securities,
                companies,
            )
            return PanelResult(
                panel=panel,
                as_of=pivot.as_of,
                pivot=pivot,
                facts=observations.facts_for_pivot(panel, pivot, unit),
            )

        spec = AnalyticSpec(
            name=panel.title,
            portfolio_filter=panel.portfolio_filter,
            security_filter=panel.security_filter,
            group_by=panel.group_by,
            metric=panel.metric,
            data_point_field_id=panel.data_point_field_id,
            as_of=panel.as_of,
            date_range=panel.date_range if panel.kind == "trend" else None,
        )
        result = analytics.execute(spec, store, securities, companies)
    except ValueError as exc:
        return PanelResult(panel=panel, error=str(exc))

    if isinstance(result, AggregationResult):
        return PanelResult(
            panel=panel,
            as_of=result.as_of,
            aggregation=result,
            facts=observations.facts_for_aggregation(panel, result, unit),
        )

    if not result:
        return PanelResult(panel=panel, trend=[], error="No snapshots fall inside the requested date range.")
    return PanelResult(
        panel=panel,
        as_of=result[-1].as_of,
        trend=result,
        facts=observations.facts_for_trend(panel, result, unit),
    )
