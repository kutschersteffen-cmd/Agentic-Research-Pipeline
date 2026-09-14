from __future__ import annotations

from arp.portfolio.genbi.schemas import DashboardFact, PanelSpec
from arp.schemas.portfolio import AggregationResult, NewsRiskFlag, PivotResult, TrendPoint

TOP_N_CONCENTRATION = 3
"""How many groups the concentration fact adds up. Three is the usual
house-view threshold for "is this exposure concentrated"; it only fires
when there are strictly more groups than that, so it never restates the
total under a different name."""


def format_money(value: float) -> str:
    return f"EUR {value:,.0f}"


def format_share(fraction: float) -> str:
    return f"{fraction * 100:.1f}%"


def format_metric_value(metric: str, value: float, unit: str = "") -> str:
    """Single place where a metric's number becomes text. `observations.py`
    renders every fact through it and `narrator.py` builds its allowed-number
    set from the same strings, so the figure a narrative may quote is
    literally the figure a fact computed -- no second, drifting formatter.
    """
    if metric == "market_value_sum":
        return format_money(value)
    if metric == "count":
        return f"{value:,.0f}"
    rendered = f"{value:,.2f}"
    return f"{rendered} {unit}".strip()


def _row_value(row, metric: str) -> float | None:
    if metric == "market_value_sum":
        return row.market_value_eur
    if metric == "count":
        return float(row.holding_count)
    return row.weighted_avg_value


def facts_for_aggregation(panel: PanelSpec, result: AggregationResult, unit: str = "") -> list[DashboardFact]:
    """Derives the figures worth saying out loud about one point-in-time
    result: the total, the biggest group and its share, how concentrated
    the top few groups are, and -- for a data-point average -- how much of
    the portfolio actually had the data point at all. Pure arithmetic over
    an already-computed result: no LLM, no store access, no re-aggregation.
    """
    facts: list[DashboardFact] = []
    metric = result.metric
    scope = f"as of {result.as_of}"

    holdings = sum(r.holding_count for r in result.rows)
    if metric == "count":
        facts.append(
            DashboardFact(
                panel_id=panel.panel_id,
                kind="total",
                label="Holdings in scope",
                value=float(holdings),
                text=f"{holdings:,.0f} holdings in scope ({scope}).",
            )
        )
    else:
        facts.append(
            DashboardFact(
                panel_id=panel.panel_id,
                kind="total",
                label="Total market value in scope",
                value=result.total_market_value_eur,
                unit="EUR",
                text=f"Total market value in scope: {format_money(result.total_market_value_eur)} across {holdings:,.0f} holdings ({scope}).",
            )
        )

    ranked = sorted(
        ((r, _row_value(r, metric)) for r in result.rows if _row_value(r, metric) is not None),
        key=lambda pair: pair[1],
        reverse=True,
    )
    if ranked:
        top_row, top_value = ranked[0]
        rendered = format_metric_value(metric, top_value, unit)
        if metric == "weighted_avg_datapoint":
            text = f"Highest {result.group_by}: {top_row.group_value} at {rendered}."
        elif metric == "count":
            text = f"Largest {result.group_by} by holding count: {top_row.group_value} with {rendered} holdings."
        elif result.total_market_value_eur:
            share = top_row.market_value_eur / result.total_market_value_eur if top_row.market_value_eur else 0.0
            text = f"Largest {result.group_by}: {top_row.group_value} at {rendered}, {format_share(share)} of the {format_money(result.total_market_value_eur)} total."
        else:
            text = f"Largest {result.group_by}: {top_row.group_value} at {rendered}."
        facts.append(
            DashboardFact(
                panel_id=panel.panel_id,
                kind="top_contributor",
                label=f"Largest {result.group_by}",
                value=top_value,
                unit=unit if metric == "weighted_avg_datapoint" else ("EUR" if metric == "market_value_sum" else ""),
                text=text,
            )
        )

    if metric == "market_value_sum" and len(ranked) > TOP_N_CONCENTRATION and result.total_market_value_eur:
        top_sum = sum(value for _row, value in ranked[:TOP_N_CONCENTRATION])
        share = top_sum / result.total_market_value_eur
        names = ", ".join(row.group_value for row, _v in ranked[:TOP_N_CONCENTRATION])
        facts.append(
            DashboardFact(
                panel_id=panel.panel_id,
                kind="concentration",
                label=f"Top {TOP_N_CONCENTRATION} {result.group_by} concentration",
                value=share,
                unit="share",
                text=f"The top {TOP_N_CONCENTRATION} {result.group_by} groups ({names}) hold {format_money(top_sum)}, {format_share(share)} of the total.",
            )
        )

    if metric == "weighted_avg_datapoint":
        covered = result.total_market_value_eur - result.unresolved_market_value_eur
        coverage = covered / result.total_market_value_eur if result.total_market_value_eur else 0.0
        facts.append(
            DashboardFact(
                panel_id=panel.panel_id,
                kind="coverage",
                label="Data-point coverage",
                value=coverage,
                unit="share",
                text=f"{format_share(coverage)} of market value in scope had a resolved value for {panel.data_point_field_id or 'the data point'}.",
            )
        )
        if result.unresolved_market_value_eur:
            facts.append(
                DashboardFact(
                    panel_id=panel.panel_id,
                    kind="unresolved",
                    label="Excluded for missing data",
                    value=result.unresolved_market_value_eur,
                    unit="EUR",
                    text=f"{format_money(result.unresolved_market_value_eur)} of market value was excluded from the average for having no value -- not counted as zero.",
                )
            )
        worst = [r for r in result.rows if r.coverage_pct is not None]
        if len(worst) > 1:
            low = min(worst, key=lambda r: r.coverage_pct)
            facts.append(
                DashboardFact(
                    panel_id=panel.panel_id,
                    kind="coverage",
                    label=f"Weakest {result.group_by} coverage",
                    value=low.coverage_pct,
                    unit="share",
                    text=f"Weakest coverage by {result.group_by}: {low.group_value} at {format_share(low.coverage_pct)}.",
                )
            )

    return facts


def facts_for_trend(panel: PanelSpec, trend: list[TrendPoint], unit: str = "") -> list[DashboardFact]:
    """Start-to-end movement of the whole series plus the group that moved
    most. Deliberately only compares the first and last snapshot in range --
    an "average trend" over irregularly spaced snapshots would be a number
    nobody could reproduce from the table underneath it.
    """
    if len(trend) < 2:
        return []
    facts: list[DashboardFact] = []
    first, last = trend[0], trend[-1]
    metric = last.result.metric

    def series_total(point: TrendPoint) -> float:
        if metric == "market_value_sum":
            return point.result.total_market_value_eur
        if metric == "count":
            return float(sum(r.holding_count for r in point.result.rows))
        values = [r.weighted_avg_value for r in point.result.rows if r.weighted_avg_value is not None]
        weights = [r.market_value_eur or 0.0 for r in point.result.rows if r.weighted_avg_value is not None]
        total_weight = sum(weights)
        if not values or not total_weight:
            return 0.0
        return sum(v * w for v, w in zip(values, weights, strict=True)) / total_weight

    start, end = series_total(first), series_total(last)
    delta = end - start
    direction = "rose" if delta > 0 else ("fell" if delta < 0 else "was unchanged")
    pct = f" ({format_share(abs(delta) / start)})" if start else ""
    facts.append(
        DashboardFact(
            panel_id=panel.panel_id,
            kind="trend_delta",
            label="Change over the period",
            value=delta,
            unit=unit or ("EUR" if metric == "market_value_sum" else ""),
            text=(
                f"Across {len(trend)} snapshots the total {direction} from {format_metric_value(metric, start, unit)} "
                f"({first.as_of}) to {format_metric_value(metric, end, unit)} ({last.as_of}), a change of "
                f"{format_metric_value(metric, abs(delta), unit)}{pct}."
            ),
        )
    )

    def group_value(point: TrendPoint, group: str) -> float | None:
        row = next((r for r in point.result.rows if r.group_value == group), None)
        return _row_value(row, metric) if row else None

    groups = {r.group_value for point in trend for r in point.result.rows}
    moves: list[tuple[str, float]] = []
    for group in sorted(groups):
        start_v, end_v = group_value(first, group), group_value(last, group)
        if start_v is None or end_v is None:
            continue
        moves.append((group, end_v - start_v))
    if moves:
        group, move = max(moves, key=lambda pair: abs(pair[1]))
        verb = "increased" if move > 0 else ("decreased" if move < 0 else "was flat")
        facts.append(
            DashboardFact(
                panel_id=panel.panel_id,
                kind="trend_mover",
                label="Largest mover",
                value=move,
                unit=unit or ("EUR" if metric == "market_value_sum" else ""),
                text=f"Largest mover by {last.result.group_by}: {group} {verb} by {format_metric_value(metric, abs(move), unit)} between {first.as_of} and {last.as_of}.",
            )
        )
    return facts


def facts_for_pivot(panel: PanelSpec, pivot: PivotResult, unit: str = "") -> list[DashboardFact]:
    """The two figures a cross-tab is usually read for: the single biggest
    cell, and the biggest row total across all columns."""
    facts: list[DashboardFact] = []
    metric = pivot.metric

    def cell_value(cell) -> float | None:
        if metric == "market_value_sum":
            return cell.market_value_eur
        if metric == "count":
            return float(cell.holding_count)
        return cell.weighted_avg_value

    cells = [(c, cell_value(c)) for c in pivot.cells]
    populated = [(c, v) for c, v in cells if v is not None]
    if not populated:
        return facts

    top_cell, top_value = max(populated, key=lambda pair: pair[1])
    facts.append(
        DashboardFact(
            panel_id=panel.panel_id,
            kind="largest_cell",
            label="Largest cell",
            value=top_value,
            unit=unit or ("EUR" if metric == "market_value_sum" else ""),
            text=(
                f"Largest {pivot.row_dim} x {pivot.col_dim} cell: {top_cell.row_value} / {top_cell.col_value} at "
                f"{format_metric_value(metric, top_value, unit)} (as of {pivot.as_of})."
            ),
        )
    )

    if metric == "market_value_sum":
        totals: dict[str, float] = {}
        for cell, value in populated:
            totals[cell.row_value] = totals.get(cell.row_value, 0.0) + value
        row_value, row_total = max(totals.items(), key=lambda pair: pair[1])
        share = row_total / pivot.total_market_value_eur if pivot.total_market_value_eur else 0.0
        facts.append(
            DashboardFact(
                panel_id=panel.panel_id,
                kind="row_total",
                label=f"Largest {pivot.row_dim} total",
                value=row_total,
                unit="EUR",
                text=f"Largest {pivot.row_dim} across all {pivot.col_dim} columns: {row_value} at {format_money(row_total)}, {format_share(share)} of {format_money(pivot.total_market_value_eur)}.",
            )
        )
    return facts


def facts_for_news_flags(flags: list[NewsRiskFlag]) -> list[DashboardFact]:
    """A dashboard-level fact (no panel) connecting the news-derived risk
    signal into the same narration surface as the holdings numbers. Only
    grounded flags count -- an ungrounded classifier output never becomes
    something the narrative can assert."""
    grounded = [f for f in flags if f.grounded]
    if not grounded:
        return []
    high = [f for f in grounded if f.severity == "high"]
    issuers = sorted({f.company_id for f in grounded})
    issuer_list = ", ".join(issuers[:5]) + (" and others" if len(issuers) > 5 else "")
    return [
        DashboardFact(
            kind="news_flags",
            label="Grounded news risk flags",
            value=float(len(grounded)),
            text=(
                f"{len(grounded)} grounded news risk flag(s) across {len(issuers)} issuer(s) ({issuer_list}); "
                f"{len(high)} rated high severity."
            ),
        )
    ]
