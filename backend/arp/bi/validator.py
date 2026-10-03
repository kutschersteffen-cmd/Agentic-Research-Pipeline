"""Checks a ChartPlan against the catalog and live dataset metadata.
Returns human-readable reasons; the planner feeds them back to the LLM."""

from __future__ import annotations

from arp.bi.catalog import VIEW_DATASETS, VIZ_ALLOWLIST
from arp.bi.plan import MAX_CHARTS, ChartPlan, DatasetMeta


def validate_plan(plan: ChartPlan, metas: dict[str, DatasetMeta]) -> list[str]:
    errors: list[str] = []
    n = len(plan.charts)
    if n == 0:
        errors.append(f"Plan has no charts; it needs between 1 and {MAX_CHARTS}.")
    elif n > MAX_CHARTS:
        errors.append(f"Plan has {n} charts; the maximum is {MAX_CHARTS}.")

    seen: set[str] = set()
    for c in plan.charts:
        t = f"Chart '{c.title}'"
        if c.title in seen:
            errors.append(f"{t}: duplicate chart title; titles must be unique.")
        seen.add(c.title)
        if c.viz_type not in VIZ_ALLOWLIST:
            errors.append(f"{t}: viz_type '{c.viz_type}' is not allowed; use one of {', '.join(VIZ_ALLOWLIST)}.")
        if c.viz_type == "pivot_table_v2" and len(c.groupby) < 2:
            errors.append(f"{t}: pivot_table_v2 needs at least two groupby columns (rows and columns).")
        if not c.metrics:
            errors.append(f"{t}: needs at least one metric.")
        meta = metas.get(c.dataset)
        if c.dataset not in VIEW_DATASETS or meta is None:
            errors.append(f"{t}: unknown dataset '{c.dataset}'; use one of {', '.join(VIEW_DATASETS)}.")
            continue
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
