"""Segment financials from dimensional XBRL facts: one row per segment per metric, latest fiscal year only."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

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
_ELIMINATIONS = {f"{p}:{n}" for p in ("us-gaap", "srt")
                 for n in ("ConsolidationEliminationsMember", "IntersegmentEliminationMember")}
_CORPORATE_ONLY = {f"{p}:{n}" for p in ("us-gaap", "srt")
                   for n in ("CorporateAndOtherMember", "CorporateMember", "CorporateNonSegmentMember")
                   } | {"ifrs-full:AllOtherSegmentsMember"}
_RECONCILING = _ELIMINATIONS | {f"{p}:{n}" for p in ("us-gaap", "srt")
                                for n in ("CorporateNonSegmentMember", "SegmentReconcilingItemsMember")}


def segment_name(member: str) -> str:
    name = re.sub(r"Member$", "", member.rpartition(":")[2])
    name = re.sub(r"Segment$", "", name)
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)


def _kept(f: DimFact, axis: str) -> bool:
    rest = {a: m for a, m in f.dims.items() if a != axis}
    return (axis in f.dims and rest in ({}, _OPERATING) and bool(f.period_start)
            and _full_year({"start": f.period_start, "end": f.period_end}))


def _reconciling(dim_facts: list[DimFact], concept: str, year: int) -> float:
    by_member: dict[str, float] = {}
    for f in dim_facts:
        m = f.dims.get("srt:ConsolidationItemsAxis")
        if (f.concept == concept and len(f.dims) == 1 and m in _RECONCILING and int(f.period_end[:4]) == year
                and f.period_start and _full_year({"start": f.period_start, "end": f.period_end})):
            by_member.setdefault(m, -abs(f.value) if m in _ELIMINATIONS else f.value)
    return sum(by_member.values())


def _drop_total_and_corporate(by_member: dict[str, DimFact]) -> dict[str, DimFact]:
    """Drop the first member equal (within 0.5%) to the sum of the others, then a lone corporate member."""
    for m, f in by_member.items():
        others = sum(g.value for k, g in by_member.items() if k != m)
        if len(by_member) > 1 and abs(f.value - others) <= 0.005 * abs(others):
            by_member = {k: g for k, g in by_member.items() if k != m}
            break
    return {} if list(by_member) in ([m] for m in _CORPORATE_ONLY) else by_member


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
                rec = _reconciling(dim_facts, concept, year) if kind == "segment" else None
                for level, by_member in groups.items():
                    if kind == "segment":
                        by_member = _drop_total_and_corporate(by_member)
                    seg_sum = sum(f.value for f in by_member.values()) + (rec or 0)
                    match = bool(total) and abs(seg_sum - total) / abs(total) <= 0.01
                    rows += [SegmentRow(
                        company_id=company_id, market=market, fiscal_year=year, metric=metric, concept=concept,
                        axis=axis, member=member, segment=segment_name(member), value=f.value, unit=f.unit,
                        period_start=f.period_start, period_end=f.period_end, accession=accession,
                        sum_matches_total=match, reconciling=rec, axis_kind=kind, level=level,
                    ) for member, f in by_member.items()]
                break
    return rows


_XL, _LINK = "{http://www.w3.org/1999/xlink}", "{http://www.xbrl.org/2003/linkbase}"
_STD_LABEL = "http://www.xbrl.org/2003/role/label"
_STANDARD_PREFIXES = ("us-gaap:", "srt:", "ifrs-full:", "country:")


def _clean_label(text: str) -> str:
    text = re.sub(r"\s*\[Member\]$", "", text.strip())
    return re.sub(r"\s+Segment$", "", text, flags=re.IGNORECASE).strip()


def label_map(xml: bytes) -> dict[str, str]:
    """Concept (x:AlphaMember) -> cleaned standard English label from a label linkbase; en-US beats other en*."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return {}  # a broken label file leaves every row derived
    locs = {e.get(f"{_XL}label"): e.get(f"{_XL}href", "").partition("#")[2].replace("_", ":", 1)
            for e in root.iter(f"{_LINK}loc")}
    to_concepts: dict[str, list[str]] = {}
    for arc in root.iter(f"{_LINK}labelArc"):
        if arc.get(f"{_XL}from") in locs:
            to_concepts.setdefault(arc.get(f"{_XL}to"), []).append(locs[arc.get(f"{_XL}from")])
    out: dict[str, str] = {}
    exact: set[str] = set()
    for e in root.iter(f"{_LINK}label"):
        lang = e.get("{http://www.w3.org/XML/1998/namespace}lang", "")
        if e.get(f"{_XL}role") != _STD_LABEL or not lang.lower().startswith("en"):
            continue
        for concept in to_concepts.get(e.get(f"{_XL}label"), []):
            if concept not in exact and (lang == "en-US" or concept not in out):
                out[concept] = _clean_label(e.text or "")
                if lang == "en-US":
                    exact.add(concept)
    return out


def _labelled(r: SegmentRow, labels: dict[str, str] | None) -> dict:
    label = (labels or {}).get(r.member)
    if not label or r.member.startswith(_STANDARD_PREFIXES):
        return {}
    return {"segment": label, "segment_source": "label"}


def sec_segments(xhtml: bytes, *, company_id: str, accession: str | None,
                 form: str | None = None, labels: dict[str, str] | None = None) -> tuple[list[SegmentRow], str | None]:
    """An annual report's segment rows and note text (None when it has none), read with the US-GAAP or the
    IFRS concept set, whichever yields more rows (a tie goes to US-GAAP)."""
    facts, dim_facts, texts = parse_ixbrl_dimensional(xhtml)
    totals: dict[tuple[str, int], float] = {}
    for f in facts:
        if f.period_start and _full_year({"start": f.period_start, "end": f.period_end}):
            totals.setdefault((f.concept, int(f.period_end[:4])), f.value)
    us, ifrs = (build_segments(dim_facts, totals, market=m, company_id=company_id, accession=accession)
                for m in ("sec", "esef"))
    win, rows = ("esef", ifrs) if len(ifrs) > len(us) else ("sec", us)
    return [r.model_copy(update={"market": "sec", "form": form, **_labelled(r, labels)}) for r in rows], texts.get(NOTE_CONCEPTS[win]) or None


def store_segments(store: XbrlStore, key: str, rows: list[SegmentRow], note: str | None) -> None:
    store.write_segments(key, rows)
    store.write_segment_note(key, note)
    counts = {k: sum(r.axis_kind == k for r in rows) for k in ("segment", "product", "geography")}
    store.update_meta(key, segment_count=counts["segment"], product_count=counts["product"],
                      geography_count=counts["geography"], segment_note_chars=len(note or ""))


def write_segments_sec(key: str, store: XbrlStore, company_id: str) -> None:
    """Segments from the stored annual report; none when it is missing or not inline XBRL."""
    meta, path = store.report_meta(key), store.file_path(key, "report")
    rows, note = ([], None)
    if meta and meta.inline_xbrl and path:
        lab = store.file_path(key, "labels")
        rows, note = sec_segments(path.read_bytes(), company_id=company_id, accession=meta.accession,
                                  form=meta.form, labels=label_map(lab.read_bytes()) if lab else None)
    store_segments(store, key, rows, note)
