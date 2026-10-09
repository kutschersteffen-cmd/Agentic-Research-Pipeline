from __future__ import annotations

from arp.ingestion.xbrl import _ANNUAL_FORMS, CAPEX_TAGS, REVENUE_TAGS, XbrlFactSource, _full_year
from arp.xbrl_pipeline.models import RequiredRow

_METRICS = (("revenue", REVENUE_TAGS), ("capex", CAPEX_TAGS))


def _annual_years(facts: dict) -> list[int]:
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    years = {
        int(r["end"][:4])
        for _, tags in _METRICS
        for tag in tags
        for rows in us_gaap.get(tag, {}).get("units", {}).values()
        for r in rows
        if r.get("form") in _ANNUAL_FORMS and r.get("fp") == "FY" and r.get("val") is not None
        and r.get("end") and _full_year(r)
    }
    return sorted(years)


def resolve_required(facts: dict, *, company_id: str, cik: str) -> list[RequiredRow]:
    """One revenue and one capex row per annual period-end year; `not_found` when no tag has it."""
    years: list[int | None] = list(_annual_years(facts)) or [None]
    out = []
    for year in years:
        for metric, tags in _METRICS:
            fact = XbrlFactSource.fact_for_tags(facts, tags, fiscal_year=year) if year is not None else None
            base = dict(company_id=company_id, cik=cik, metric=metric, fiscal_year=year)
            if fact is None:
                out.append(RequiredRow(**base, status="not_found", concept=None, value=None, unit=None,
                                       period_start=None, period_end=None, form=None, filed=None))
            else:
                out.append(RequiredRow(**base, status="found", concept=f"us-gaap:{fact.tag}", value=fact.value,
                                       unit=fact.unit, period_start=fact.period_start,
                                       period_end=fact.period_end, form=fact.form, filed=fact.filed))
    return out
