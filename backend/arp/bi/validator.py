"""Checks a ChartPlan against the catalog and live dataset metadata.
Returns human-readable reasons; the planner feeds them back to the LLM."""

from __future__ import annotations

from arp.bi.catalog import MAX_GROUPBY, MAX_METRICS, MIN_GROUPBY, TEMPORAL_COLUMNS, VIEW_DATASETS, VIZ_ALLOWLIST
from arp.bi.plan import MAX_CHARTS, ChartPlan, DatasetMeta


def validate_plan(plan: ChartPlan, metas: dict[str, DatasetMeta], max_charts: int = MAX_CHARTS) -> list[str]:
    """`max_charts` caps a planner's output; a committed template passes its own size."""
    errors: list[str] = []
    n = len(plan.charts)
    if n == 0:
        errors.append(f"Plan has no charts; it needs between 1 and {max_charts}.")
    elif n > max_charts:
        errors.append(f"Plan has {n} charts; the maximum is {max_charts}.")

    seen: set[str] = set()
    for c in plan.charts:
        t = f"Chart '{c.title}'"
        if c.title in seen:
            errors.append(f"{t}: duplicate chart title; titles must be unique.")
        seen.add(c.title)
        if c.viz_type not in VIZ_ALLOWLIST:
            errors.append(f"{t}: viz_type '{c.viz_type}' is not allowed; use one of {', '.join(VIZ_ALLOWLIST)}.")
        lo, hi = MIN_GROUPBY.get(c.viz_type, 0), MAX_GROUPBY.get(c.viz_type)
        if len(c.groupby) < lo:
            errors.append(f"{t}: {c.viz_type} needs at least {lo} groupby column(s); got {len(c.groupby)}.")
        if hi == 0 and c.groupby:
            errors.append(f"{t}: {c.viz_type} takes no groupby columns; got {', '.join(c.groupby)}.")
        elif hi is not None and len(c.groupby) > hi:
            errors.append(f"{t}: {c.viz_type} takes at most {hi} groupby columns; got {', '.join(c.groupby)}.")
        if not c.metrics:
            errors.append(f"{t}: needs at least one metric.")
        elif MAX_METRICS.get(c.viz_type) == 1 and len(c.metrics) > 1:
            errors.append(f"{t}: {c.viz_type} takes exactly one metric; got {', '.join(c.metrics)}.")
        meta = metas.get(c.dataset)
        if c.dataset not in VIEW_DATASETS or meta is None:
            errors.append(f"{t}: unknown dataset '{c.dataset}'; use one of {', '.join(VIEW_DATASETS)}.")
            continue
        if c.viz_type == "echarts_timeseries_line" and c.groupby and c.groupby[0] not in TEMPORAL_COLUMNS[c.dataset]:
            errors.append(
                f"{t}: echarts_timeseries_line needs a date column first in groupby; '{c.groupby[0]}' is not one "
                f"in dataset '{c.dataset}' (date columns: {', '.join(sorted(TEMPORAL_COLUMNS[c.dataset]))})."
            )
        if c.dataset == "holdings_history" and c.groupby[:1] != ["as_of_date"]:
            errors.append(
                f"{t}: dataset 'holdings_history' holds every snapshot, so it is for charts over time only and "
                "needs 'as_of_date' as its first groupby column; anything else sums across snapshots and "
                "double-counts. Use dataset 'holdings' for a single as-of view."
            )
        errors += [
            f"{t}: unknown metric '{m}' for dataset '{c.dataset}'; available: {', '.join(sorted(meta.metrics))}."
            for m in c.metrics
            if m not in meta.metrics
        ]
        errors += [
            f"{t}: unknown {kind} column '{col}' in dataset '{c.dataset}'; available: {', '.join(sorted(meta.columns))}."
            for kind, cols in (("groupby", c.groupby), ("filter", c.filters))
            for col in cols
            if col not in meta.columns
        ]
    return errors
