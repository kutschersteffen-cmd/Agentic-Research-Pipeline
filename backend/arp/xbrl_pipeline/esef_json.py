"""filings.xbrl.org xBRL-JSON to FactRow lists (plain numeric facts only)."""

from __future__ import annotations

import math
from datetime import date, timedelta

from arp.ingestion.xbrl import _full_year
from arp.xbrl_pipeline.models import CatalogEntry, FactRow

_PLAIN = {"concept", "entity", "period", "unit"}


def _prev_day(ts: str) -> str:
    # xBRL-JSON writes a period end as the start of the next day (end exclusive).
    return (date.fromisoformat(ts[:10]) - timedelta(days=1)).isoformat()


def parse_period(period: str) -> tuple[str | None, str]:
    if "/" in period:
        start, end = period.split("/", 1)
        return start[:10], _prev_day(end)
    return None, _prev_day(period)


def _number(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def flatten_xbrl_json(
    doc: dict, *, company_id: str, lei: str, source_sha: str, filing: dict
) -> tuple[list[FactRow], int]:
    rows: list[FactRow] = []
    seen: set[tuple] = set()
    skipped = 0
    for fact in (doc.get("facts") or {}).values():
        dims = fact.get("dimensions") or {}
        value = _number(fact.get("value"))
        if value is None or not dims.get("unit"):
            continue
        if not set(dims) <= _PLAIN:
            skipped += 1
            continue
        taxonomy, _, concept = dims["concept"].partition(":")
        unit = dims["unit"].split(":", 1)[-1]
        start, end = parse_period(dims["period"])
        key = (taxonomy, concept, unit, start, end)
        if key in seen:
            continue
        seen.add(key)
        annual = _full_year({"start": start, "end": end})
        rows.append(
            FactRow(
                company_id=company_id,
                cik=lei,
                taxonomy=taxonomy,
                concept=concept,
                unit=unit,
                value=value,
                period_start=start,
                period_end=end,
                fiscal_year=int(end[:4]),
                fiscal_period="FY" if annual else None,
                form="ESEF",
                filed=filing["date_added"][:10],
                accession=filing["fxo_id"],
                source_sha=source_sha,
                market="esef",
            )
        )
    return rows, skipped


def catalog_from_rows(rows: list[FactRow]) -> list[CatalogEntry]:
    groups: dict[tuple[str, str], list[FactRow]] = {}
    for r in rows:
        groups.setdefault((r.taxonomy, r.concept), []).append(r)
    out = []
    for (taxonomy, concept), rs in groups.items():
        years = [r.fiscal_year for r in rs if r.fiscal_year is not None]
        out.append(
            CatalogEntry(
                taxonomy=taxonomy,
                concept=concept,
                label=None,
                fact_count=len(rs),
                first_year=min(years, default=None),
                last_year=max(years, default=None),
                units=list(dict.fromkeys(r.unit for r in rs)),
            )
        )
    return out
