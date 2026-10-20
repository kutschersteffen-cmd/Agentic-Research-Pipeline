from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException

from arp.api.deps import get_portfolio_store
from arp.api.routers.companies import _resolve
from arp.db import company_view as view
from arp.db import models as m
from arp.db.session import transaction
from arp.presets.transition_capex import BOOLEAN_FIELDS, FIELD_IDS
from arp.schemas.common import CompanyRef
from arp.schemas.transition_alignment import (
    BenchmarkOut,
    BenchmarksOut,
    RedlineDef,
    RndTestDef,
    SectorBenchmarksOut,
    TransitionOut,
)
from arp.transition_alignment.benchmarks import citation, load_benchmarks, sector_for_isic
from arp.transition_alignment.capex import Fact, score_capex
from arp.transition_barrier import dataset
from arp.transition_barrier.render import fmt_number
from arp.transition_barrier.rule_book import load_rule_book

router = APIRouter(prefix="/api", tags=["transition-alignment"])

_COUNTED = {m.FactStatus.APPROVED, m.FactStatus.AUTO_ACCEPTED, m.FactStatus.EDITED}
_BOOLS = {"true": True, "yes": True, "false": False, "no": False}


@router.get("/transition-alignment/benchmarks", response_model=BenchmarksOut)
def get_benchmarks() -> BenchmarksOut:
    b = load_benchmarks()
    return BenchmarksOut(
        version=b.version,
        licence_note=b.licence_note,
        sectors=[
            SectorBenchmarksOut(
                sector=name,
                isic_prefixes=s.isic_prefixes,
                capex=BenchmarkOut(
                    value=s.capex.value,
                    unit=s.capex.unit,
                    method=s.capex.method,
                    citation=citation(s.capex.source),
                    url=s.capex.source.url,
                    licence=s.capex.licence,
                ),
                rnd_tests=[
                    RndTestDef(
                        **t.model_dump(include={"id", "label", "numerator", "denominator", "value", "unit"}),
                        citation=citation(t.source),
                    )
                    for t in s.rnd_tests
                ],
                redlines=[RedlineDef(id=r.id, label=r.label, fact=r.fact, citation=citation(r.source)) for r in s.redlines],
            )
            for name, s in b.sectors.items()
        ],
    )


def _decimal(v) -> Decimal | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        d = Decimal(str(v).replace(",", ""))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _fact(r: view.CompanyFactRow) -> Fact:
    year = r.period_end.year if r.period_end else None  # R4: fiscal year = period_end.year
    if r.field_id in BOOLEAN_FIELDS:
        value = r.value if isinstance(r.value, bool) else _BOOLS.get(str(r.value).strip().casefold())
        shown = {True: "Yes", False: "No"}.get(value, "")
        return Fact(r.fact_id, r.field_id, year, value, None, None, shown, r.source_label)
    value = _decimal(r.value)
    if r.canonical_value is not None:
        amount, unit = Decimal(str(r.canonical_value)), r.canonical_unit
    else:
        amount, unit = value, r.unit
    shown = "" if value is None else f"{fmt_number(float(value))} {r.unit}" if r.unit else fmt_number(float(value))
    return Fact(r.fact_id, r.field_id, year, value, amount, unit, shown, r.source_label)


def _company_facts(s, cid) -> list[Fact]:
    """The counted current `tc_*` facts, one per (field, year): basis "" first, else the lowest fact_id (R4)."""
    rows = [r for fid in FIELD_IDS for r in view.facts(s, cid, field_id=fid, limit=500) if r.status in _COUNTED]
    picked: dict[tuple, view.CompanyFactRow] = {}
    for r in sorted(rows, key=lambda r: (r.basis != "", r.fact_id)):
        picked.setdefault((r.field_id, r.period_end.year if r.period_end else None), r)
    return [_fact(r) for r in picked.values()]


@router.get("/companies/{ref}/transition", response_model=TransitionOut)
def get_company_transition(ref: str) -> TransitionOut:
    b = load_benchmarks()
    versions = dict(benchmarks_version=b.version, rule_book_version=load_rule_book(dataset.data_dir())[0].version)
    with transaction() as s:
        cid = _resolve(s, ref)
        isic = s.get(m.Company, cid).isic_code
        sector = sector_for_isic(b, isic)
        if sector is None:
            reason = f"ISIC {isic} is not in a transition-barrier sector" if isic else "No ISIC code"
            return TransitionOut(in_scope=False, reason=reason, sector=None, capex=None, **versions)
        facts = _company_facts(s, cid)
    capex = score_capex(facts, b.sectors[sector], b.licence_note)
    return TransitionOut(in_scope=True, reason=None, sector=sector, capex=capex, **versions)


@router.get("/transition-alignment/sectors/{sector}/companies", response_model=list[CompanyRef])
def get_sector_companies(sector: str, store=Depends(get_portfolio_store)) -> list[CompanyRef]:
    """R11: the in-scope portfolio companies of a sector, for a run of the presets via POST /api/extraction/start."""
    b = load_benchmarks()
    if sector not in b.sectors:
        raise HTTPException(404, f"Unknown sector: {sector}")
    return [c for c in store.list_companies() if sector_for_isic(b, c.isic_code) == sector]
