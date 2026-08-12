from __future__ import annotations

import csv
from pathlib import Path

from arp.schemas.revenue_exposure import CatalogueDataPoint, RevenueCapexMetric

_TOTAL_LABELS = {"revenue": "Total Revenue", "capex": "Total CapEx"}


def load_catalogue(path: Path) -> list[CatalogueDataPoint]:
    """Loads a user-supplied structured revenue/capex catalogue CSV.

    Columns: data_point_id, company_id, metric (revenue|capex), label,
    description, value, unit, period, as_pct_of_total (optional). One row
    per line item; a company's `label="Total Revenue"`/`"Total CapEx"` row
    (if present) is the denominator used to compute a share for rows that
    don't already carry `as_pct_of_total`.
    """
    points: list[CatalogueDataPoint] = []
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            pct_raw = (row.get("as_pct_of_total") or "").strip()
            value_raw = (row.get("value") or "").strip()
            points.append(
                CatalogueDataPoint(
                    data_point_id=row["data_point_id"].strip(),
                    company_id=row["company_id"].strip(),
                    metric=row["metric"].strip(),
                    label=row["label"].strip(),
                    description=(row.get("description") or "").strip(),
                    value=float(value_raw) if value_raw else None,
                    unit=(row.get("unit") or "USD").strip(),
                    period=(row.get("period") or "").strip(),
                    as_pct_of_total=float(pct_raw) if pct_raw else None,
                )
            )
    return points


def distinct_labels(catalogue: list[CatalogueDataPoint], metric: RevenueCapexMetric) -> list[str]:
    """The closed list of category/segment labels used for `metric` across
    the whole catalogue -- what the mapping-suggestion LLM call selects
    from, and what a returned label is validated against."""
    seen: dict[str, None] = {}
    for point in catalogue:
        if point.metric == metric and point.label != _TOTAL_LABELS.get(metric):
            seen.setdefault(point.label, None)
    return list(seen)


def by_company(catalogue: list[CatalogueDataPoint]) -> dict[str, list[CatalogueDataPoint]]:
    grouped: dict[str, list[CatalogueDataPoint]] = {}
    for point in catalogue:
        grouped.setdefault(point.company_id, []).append(point)
    return grouped


def total_value(company_rows: list[CatalogueDataPoint], metric: RevenueCapexMetric) -> float | None:
    """The company's total-revenue/total-capex denominator row, if present."""
    for row in company_rows:
        if row.metric == metric and row.label == _TOTAL_LABELS[metric]:
            return row.value
    return None
