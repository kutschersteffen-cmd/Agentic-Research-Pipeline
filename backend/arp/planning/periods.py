"""Period planning (E65): which periods a document should cover, from its text alone. No model call.
The plan is a hint for extraction; it never overrides a period the text resolved."""

from __future__ import annotations

import re

from arp.ingestion.doc_identity import reporting_year
from arp.normalise.period import resolve_period
from arp.schemas.common import PeriodPlan, SourceDocument

MAX_COMPARATIVES = 4


def _end(year: int, fye: str | None) -> str | None:
    d = resolve_period(f"FY{year}", fiscal_year_end=fye).end
    return d.isoformat() if d else None


def plan_periods(doc: SourceDocument, *, fiscal_year_end: str | None, recorded: set[str]) -> PeriodPlan:
    # ponytail: year-token heuristic, use parsed table headers once the parser exposes tables
    year = reporting_year(doc.title, doc.full_text)
    if year is None:
        return PeriodPlan()
    text = doc.full_text
    lines = text.splitlines()
    comparatives: list[str] = []
    for y in range(year - 1, year - MAX_COMPARATIVES - 1, -1):
        token = rf"(?<!\d){y}(?!\d)"
        header = any(re.search(rf"(?<!\d){year}(?!\d)", ln) and re.search(token, ln) for ln in lines)
        stated = header or re.search(rf"FY ?{y}(?!\d)|year ended[^\n]*{token}", text, re.I)
        if stated and (end := _end(y, fiscal_year_end)):
            comparatives.append(end)
    current = _end(year, fiscal_year_end)
    planned = [p for p in (current, *comparatives) if p]
    return PeriodPlan(current=current, comparatives=comparatives, missing=[p for p in planned if p not in recorded])


def union_planned(docs: list[SourceDocument]) -> list[str]:
    return sorted({p for d in docs if d.period_plan for p in d.period_plan.planned}, reverse=True)
