"""D01.a low-carbon capex score, R&D tests and redlines over counted `tc_*` facts (spec section 3). Pure: no DB, no model.

Arithmetic is Decimal; floats appear only in the response models, so 30/50 serves as 60, not 60.00000000000001.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from arp.presets.transition_capex import AMOUNT_FIELDS
from arp.schemas.transition_alignment import (
    AmountOut,
    BenchmarkOut,
    CapexOut,
    RedlineOut,
    RndResultOut,
    ShareOut,
)
from arp.transition_alignment.benchmarks import RndTest, SectorEntry, citation
from arp.transition_barrier.render import fmt_number

NO_CAPEX_SHARE = "No reporting-year low-carbon capex share"
NO_RND = "No reporting-year R&D figures"
_RY_FIELDS = ("tc_capex_total", "tc_lowcarbon_capex", "tc_lowcarbon_capex_share_pct")
# Rule texts: only RY known, then the later year higher / equal / lower. D01.a pairs RY with RY+1; R&D, RY-1 with RY.
_D01A_RULES = ("Only RY known: RY used", "RY+1 higher: RY+1 used", "RY+1 equal: RY used", "RY+1 lower: average of RY and RY+1")
_RND_RULES = ("Only RY known: RY used", "RY higher: RY used", "RY equal: RY used", "RY lower: average of RY-1 and RY")

Index = dict[tuple[str, int], "Fact"]


@dataclass(frozen=True)
class Fact:
    fact_id: int
    field_id: str
    year: int | None
    value: Any  # plan text and enum fields keep the raw string
    amount: Decimal | None  # canonical value if set, else the numeric value; None for booleans
    unit: str | None  # canonical unit if set, else the observation unit
    shown: str  # "<fmt_number(value)> <observation unit>", or Yes / No
    citation: str | None
    basis: str = ""  # plan list items: `action:...` groups one action's facts; `region:<Region>` / `region:any`
    page: int | None = None  # the primary citation's page


def combine_years(earlier: Decimal | None, later: Decimal | None) -> Decimal | None:
    """R7: later if higher (or equal), the average if lower; a missing year leaves the other."""
    if earlier is None or later is None:
        return later if earlier is None else earlier
    return later if later >= earlier else (earlier + later) / 2


def _rule(earlier: Decimal | None, later: Decimal, texts: tuple[str, ...]) -> str:
    """The rule text for two years whose `later` is known: index 0 when `earlier` is missing, then higher, equal, lower."""
    if earlier is None:
        return texts[0]
    return texts[1] if later > earlier else texts[2] if later == earlier else texts[3]


def _ratio(num: Fact | None, den: Fact | None) -> Decimal | None:
    """num ÷ den × 100 when both are counted amounts in the same unit and den is not 0; never mixes currencies."""
    if num is None or den is None or num.amount is None or den.amount is None:
        return None
    if num.unit != den.unit or den.amount == 0:
        return None
    return num.amount / den.amount * 100


def _share(facts: Index, year: int, planned: bool) -> tuple[Decimal, ShareOut] | None:
    sfx = "_planned" if planned else ""
    disclosed = facts.get((f"tc_lowcarbon_capex_share_pct{sfx}", year))
    if disclosed is not None and disclosed.amount is not None:
        return disclosed.amount, ShareOut(value=float(disclosed.amount), source="disclosed", fact_ids=[disclosed.fact_id])
    low = facts.get((f"tc_lowcarbon_capex{sfx}", year))
    total = facts.get((f"tc_capex_total{sfx}", year))
    value = _ratio(low, total)
    if value is None:
        return None
    return value, ShareOut(value=float(value), source="computed from amounts", fact_ids=[low.fact_id, total.fact_id])


def share_for(facts: Index, year: int, planned: bool) -> ShareOut | None:
    """The low-carbon capex share for a year: disclosed wins; else computed from the two amounts."""
    found = _share(facts, year, planned)
    return found[1] if found else None


def _index(facts: list[Fact]) -> Index:
    """One fact per (field, year): the lowest fact_id (R4; the caller drops non-"" bases first)."""
    out: Index = {}
    for f in sorted(facts, key=lambda f: f.fact_id):
        if f.year is not None:
            out.setdefault((f.field_id, f.year), f)
    return out


def _rnd_year(facts: Index, t: RndTest, year: int) -> tuple[Decimal | None, list[int]]:
    if (t.numerator, t.denominator) == ("tc_lowcarbon_rnd", "tc_rnd_total"):  # R6: the disclosed share stands in
        share = facts.get(("tc_lowcarbon_rnd_share_pct", year))
        if share is not None and share.amount is not None:
            return share.amount, [share.fact_id]
    num, den = facts.get((t.numerator, year)), facts.get((t.denominator, year))
    value = _ratio(num, den)
    return value, ([] if value is None else [num.fact_id, den.fact_id])


def _rnd_test(facts: Index, t: RndTest, ry: int | None) -> RndResultOut:
    bench = Decimal(str(t.value))
    base = dict(id=t.id, label=t.label, benchmark=t.value)
    latest, ids = _rnd_year(facts, t, ry) if ry is not None else (None, [])
    if latest is None:
        return RndResultOut(**base, used=None, rule=None, ratio=None, ratio_shown=None, not_scored=NO_RND, fact_ids=[])
    earlier, earlier_ids = _rnd_year(facts, t, ry - 1)
    used = combine_years(earlier, latest)
    ratio = min(used / bench, Decimal(1))
    return RndResultOut(
        **base, used=float(used), rule=_rule(earlier, latest, _RND_RULES), ratio=float(ratio),
        ratio_shown=fmt_number(float(ratio)), not_scored=None, fact_ids=earlier_ids + ids,
    )


def _redlines(facts: list[Fact], sector: SectorEntry) -> list[RedlineOut]:
    out = []
    for r in sector.redlines:
        # R5: the latest counted fact across years (undated oldest); lowest fact_id within a year.
        # Only a real Yes/No counts, so an unreadable newer value never hides an older one; none is no disclosure.
        f = min((f for f in facts if f.field_id == r.fact and isinstance(f.value, bool)),
                default=None, key=lambda f: (-(f.year or 0), f.fact_id))
        status = "no disclosure" if f is None else "breached" if f.value is True else "not breached"
        out.append(RedlineOut(
            id=r.id, label=r.label, status=status, text=r.label, citation=f.citation if f else None,
            fact_id=f.fact_id if f else None, source=citation(r.source),
        ))
    return out


def score_capex(facts: list[Fact], sector: SectorEntry, licence_note: str) -> CapexOut:
    """D01.a over the counted facts of one company in `sector`; facts must already be counted (status, valid_to)."""
    idx = _index(facts)
    ry = max((y for (fid, y) in idx if fid in _RY_FIELDS), default=None)
    ry_found = _share(idx, ry, planned=False) if ry is not None else None
    ry1_found = _share(idx, ry + 1, planned=True) if ry is not None else None
    cb = sector.capex
    benchmark = BenchmarkOut(
        value=cb.value, unit=cb.unit, method=cb.method, citation=citation(cb.source), url=cb.source.url, licence=cb.licence
    )

    share_used = rule = ratio = not_scored = None
    if ry_found is None:
        not_scored = NO_CAPEX_SHARE
        headline = f"Capex not scored: {NO_CAPEX_SHARE}"
    else:
        ry_v, ry1_v = ry_found[0], ry1_found[0] if ry1_found else None
        share_used = combine_years(ry_v, ry1_v)
        rule = _D01A_RULES[0] if ry1_v is None else _rule(ry_v, ry1_v, _D01A_RULES)
        ratio = min(share_used / Decimal(str(cb.value)), Decimal(1))
        headline = f"Low-carbon capex {fmt_number(float(share_used))}% vs benchmark {fmt_number(cb.value)}%: {fmt_number(float(ratio))}"

    years = () if ry is None else (ry - 1, ry, ry + 1)
    amounts = [
        AmountOut(field_id=fid, year=y, shown=f.shown, fact_id=f.fact_id, citation=f.citation)
        for fid in AMOUNT_FIELDS
        for y in years
        if (f := idx.get((fid, y))) is not None
    ]
    return CapexOut(
        reporting_year=ry, share_ry=ry_found[1] if ry_found else None, share_ry1=ry1_found[1] if ry1_found else None,
        share_used=None if share_used is None else float(share_used),
        share_used_shown=None if share_used is None else fmt_number(float(share_used)),
        rule=rule, benchmark=benchmark,
        ratio=None if ratio is None else float(ratio),
        ratio_shown=None if ratio is None else fmt_number(float(ratio)),
        not_scored=not_scored, headline=headline, amounts=amounts,
        rnd_tests=[_rnd_test(idx, t, ry) for t in sector.rnd_tests],
        redlines=_redlines(facts, sector), licence_note=licence_note,
    )
