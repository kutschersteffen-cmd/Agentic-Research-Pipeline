from __future__ import annotations

from arp.ingestion.xbrl import _ANNUAL_FORMS, CAPEX_TAGS, REVENUE_TAGS, XbrlFactSource, _full_year
from arp.xbrl_pipeline.models import FactRow, RequiredRow

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


IFRS_REVENUE_TAGS = ["Revenue", "RevenueFromContractsWithCustomers"]
IFRS_CAPEX_TAGS = ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"]
_ESEF_METRICS = (("revenue", IFRS_REVENUE_TAGS), ("capex", IFRS_CAPEX_TAGS))


def resolve_required_esef(rows: list[FactRow], *, company_id: str, lei: str) -> list[RequiredRow]:
    """ESEF twin of `resolve_required`: per period-end year, the first IFRS candidate with a full-year
    duration fact wins (instants carry no start and do not count)."""
    best: dict[tuple[str, int], FactRow] = {}
    for metric, tags in _ESEF_METRICS:
        for tag in tags:
            for r in rows:
                if (r.taxonomy == "ifrs-full" and r.concept == tag and r.period_start
                        and _full_year({"start": r.period_start, "end": r.period_end})):
                    best.setdefault((metric, int(r.period_end[:4])), r)
    years: list[int | None] = sorted({y for _, y in best}) or [None]
    out = []
    for year in years:
        for metric, _ in _ESEF_METRICS:
            f = best.get((metric, year)) if year is not None else None
            base = dict(company_id=company_id, cik=lei, metric=metric, fiscal_year=year, market="esef")
            if f is None:
                out.append(RequiredRow(**base, status="not_found", concept=None, value=None, unit=None,
                                       period_start=None, period_end=None, form=None, filed=None))
            else:
                out.append(RequiredRow(**base, status="found", concept=f"ifrs-full:{f.concept}", value=f.value,
                                       unit=f.unit, period_start=f.period_start, period_end=f.period_end,
                                       form=f.form, filed=f.filed))
    return out
