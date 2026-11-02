"""Segment financials from dimensional XBRL facts: one row per segment per metric, latest fiscal year only."""

from __future__ import annotations

import re

from arp.ingestion.esef import DimFact, parse_ixbrl_dimensional
from arp.ingestion.xbrl import CAPEX_TAGS, REVENUE_TAGS, RND_TAGS, _full_year
from arp.xbrl_pipeline.models import Market, SegmentRow
from arp.xbrl_pipeline.required import IFRS_CAPEX_TAGS, IFRS_REVENUE_TAGS
from arp.xbrl_pipeline.store import XbrlStore


def _us(*names: str) -> list[str]:
    return [f"us-gaap:{n}" for n in names]


def _ifrs(*names: str) -> list[str]:
    return [f"ifrs-full:{n}" for n in names]


# Every name not already in the code was checked against the us-gaap 2026 / ifrs-full 2025 snapshots.
SEC_METRICS: list[tuple[str, list[str]]] = [
    ("revenue", _us(*REVENUE_TAGS)),
    ("capex", _us(*CAPEX_TAGS)),
    ("rnd", _us(*RND_TAGS)),
    ("opex", _us("OperatingExpenses", "CostsAndExpenses")),
    ("cost_of_revenue", _us("CostOfRevenue", "CostOfGoodsAndServicesSold")),
    ("sga", _us("SellingGeneralAndAdministrativeExpense")),
]
ESEF_METRICS: list[tuple[str, list[str]]] = [  # no opex: IFRS has no total operating expense concept
    ("revenue", _ifrs(*IFRS_REVENUE_TAGS)),
    ("capex", _ifrs(*IFRS_CAPEX_TAGS, "AdditionsToNoncurrentAssets")),  # IFRS 8 additions as fallback
    ("rnd", _ifrs("ResearchAndDevelopmentExpense")),
    ("cost_of_revenue", _ifrs("CostOfSales")),
    ("sga", _ifrs("SellingGeneralAndAdministrativeExpense")),
]
# ESEF product/geography axes checked against full_ifrs-cor_2025-03-27.xsd.
AXES: dict[str, dict[str, str]] = {
    "sec": {"segment": "us-gaap:StatementBusinessSegmentsAxis", "product": "srt:ProductOrServiceAxis",
            "geography": "srt:StatementGeographicalAxis"},
    "esef": {"segment": "ifrs-full:SegmentsAxis", "product": "ifrs-full:ProductsAndServicesAxis",
             "geography": "ifrs-full:GeographicalAreasAxis"},
}
_STANDARD_PREFIXES = ("us-gaap:", "srt:", "ifrs-full:")
NOTE_CONCEPTS = {"sec": "us-gaap:SegmentReportingDisclosureTextBlock",
                 "esef": "ifrs-full:DisclosureOfOperatingSegmentsExplanatory"}
# Filers like Apple tag every segment fact with this pair as well; any other second dimension is dropped.
_OPERATING = {"srt:ConsolidationItemsAxis": "us-gaap:OperatingSegmentsMember"}


def segment_name(member: str) -> str:
    name = re.sub(r"Member$", "", member.rpartition(":")[2])
    name = re.sub(r"Segment$", "", name)
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)


def _kept(f: DimFact, axis: str) -> bool:
    rest = {a: m for a, m in f.dims.items() if a != axis}
    return (axis in f.dims and rest in ({}, _OPERATING) and bool(f.period_start)
            and _full_year({"start": f.period_start, "end": f.period_end}))


def build_segments(dim_facts: list[DimFact], totals: dict[tuple[str, int], float], *, market: Market,
                   company_id: str, accession: str | None, fiscal_year: int | None = None) -> list[SegmentRow]:
    """`totals`: (concept, fiscal year) -> the non-dimensional full-year value."""
    kept = {kind: [f for f in dim_facts if _kept(f, axis)] for kind, axis in AXES[market].items()}
    if not any(kept.values()):
        return []
    # one year per filing, so product and geography rows never disagree with segment rows
    year = fiscal_year or max(int(f.period_end[:4]) for f in kept["segment"] or sum(kept.values(), []))
    metrics = SEC_METRICS if market == "sec" else ESEF_METRICS
    rows = []
    for kind, axis in AXES[market].items():
        facts = [f for f in kept[kind] if int(f.period_end[:4]) == year]
        for metric, concepts in metrics if kind == "segment" else metrics[:1]:  # revenue only off-segment
            for concept in concepts:
                groups: dict[str | None, dict[str, DimFact]] = {}
                for f in facts:
                    if f.concept == concept:
                        member = f.dims[axis]
                        level = None if kind != "product" else (
                            "standard" if member.startswith(_STANDARD_PREFIXES) else "company")
                        groups.setdefault(level, {}).setdefault(member, f)  # a fact printed twice is one row
                if not groups:
                    continue
                total = totals.get((concept, year))
                for level, by_member in groups.items():
                    match = bool(total) and abs(sum(f.value for f in by_member.values()) - total) / abs(total) <= 0.01
                    rows += [SegmentRow(
                        company_id=company_id, market=market, fiscal_year=year, metric=metric, concept=concept,
                        axis=axis, member=member, segment=segment_name(member), value=f.value, unit=f.unit,
                        period_start=f.period_start, period_end=f.period_end, accession=accession,
                        sum_matches_total=match, axis_kind=kind, level=level,
                    ) for member, f in by_member.items()]
                break
    return rows


def sec_segments(xhtml: bytes, *, company_id: str, accession: str | None) -> tuple[list[SegmentRow], str | None]:
    """A 10-K's segment rows and its segment note text (None when it has none)."""
    facts, dim_facts, texts = parse_ixbrl_dimensional(xhtml)
    totals: dict[tuple[str, int], float] = {}
    for f in facts:
        if f.period_start and _full_year({"start": f.period_start, "end": f.period_end}):
            totals.setdefault((f.concept, int(f.period_end[:4])), f.value)
    rows = build_segments(dim_facts, totals, market="sec", company_id=company_id, accession=accession)
    return rows, texts.get(NOTE_CONCEPTS["sec"]) or None


def store_segments(store: XbrlStore, key: str, rows: list[SegmentRow], note: str | None) -> None:
    store.write_segments(key, rows)
    store.write_segment_note(key, note)
    counts = {k: sum(r.axis_kind == k for r in rows) for k in ("segment", "product", "geography")}
    store.update_meta(key, segment_count=counts["segment"], product_count=counts["product"],
                      geography_count=counts["geography"], segment_note_chars=len(note or ""))


def write_segments_sec(key: str, store: XbrlStore, company_id: str) -> None:
    """Segments from the stored 10-K; none when it is missing or not inline XBRL."""
    meta, path = store.report_meta(key), store.file_path(key, "report")
    rows, note = ([], None)
    if meta and meta.inline_xbrl and path:
        rows, note = sec_segments(path.read_bytes(), company_id=company_id, accession=meta.accession)
    store_segments(store, key, rows, note)
