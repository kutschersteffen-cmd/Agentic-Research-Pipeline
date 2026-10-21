from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from arp.api.deps import get_portfolio_store, get_run_store
from arp.api.routers.companies import _resolve
from arp.db import company_view as view
from arp.db import models as m
from arp.db.documents import get_document
from arp.db.session import transaction
from arp.presets import transition_plan_actions as plan
from arp.presets.transition_capex import BOOLEAN_FIELDS, FIELD_IDS
from arp.schemas.common import CompanyRef, DocType
from arp.schemas.transition_alignment import (
    BenchmarkOut,
    BenchmarksOut,
    RedlineDef,
    RndTestDef,
    ScenarioGroupOut,
    SectorBenchmarksOut,
    TransitionOut,
)
from arp.transition_alignment.actions import Cell, CellLookup, _first, score_plan
from arp.transition_alignment.benchmarks import citation, load_benchmarks, sector_for_isic
from arp.transition_alignment.capex import Fact, score_capex
from arp.transition_alignment.delivery import scenario_entries, score_coverage, score_phaseouts, score_targets
from arp.transition_alignment.flags import score_flags
from arp.transition_barrier import dataset
from arp.transition_barrier.ratings import Ratings
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
        scenario_prices=[
            ScenarioGroupOut(group=g.group, citation=citation(g.source), prices=g.prices) for g in b.scenario_prices
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


def _fact(r: view.CompanyFactRow, booleans=BOOLEAN_FIELDS) -> Fact:
    year = r.period_end.year if r.period_end else None  # R4: fiscal year = period_end.year
    if r.field_id in booleans:
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


_EMISSIONS = ("tp_h_scope1_emissions", "tp_h_scope2_emissions")


def _company_facts(s, cid, field_ids=FIELD_IDS, booleans=BOOLEAN_FIELDS) -> list[Fact]:
    """The counted current facts of `field_ids`, one per (field, year): basis "" first, else the lowest fact_id (R4)."""
    rows = [r for fid in field_ids for r in view.facts(s, cid, field_id=fid, limit=500) if r.status in _COUNTED]
    picked: dict[tuple, view.CompanyFactRow] = {}
    for r in sorted(rows, key=lambda r: (r.basis != "", r.fact_id)):
        picked.setdefault((r.field_id, r.period_end.year if r.period_end else None), r)
    return [_fact(r, booleans) for r in picked.values()]


_INDICATORS = ("tp_a_ambition_3", "tp_a_offsetting_13")  # A_ambition_3, A_offsetting_13 (transition_plan_indicators)


def _indicator(facts: list[Fact], field_id: str) -> Fact | None:
    """F1: read as a redline reads its fact (R5): the latest counted real Yes/No, the lowest fact_id within a year."""
    return min((f for f in facts if f.field_id == field_id and isinstance(f.value, bool)),
               default=None, key=lambda f: (-(f.year or 0), f.fact_id))


_RAW = {"ta_action_text", "ta_action_id", "ta_action_status", "ta_action_region", "ta_target_scope",
        "ta_phaseout_activity", "ta_phaseout_method"}  # text and enum: the raw string


def _plan_fact(r: view.CompanyFactRow) -> Fact:
    if r.field_id in _RAW:
        f = Fact(r.fact_id, r.field_id, None, r.value, None, None, str(r.value), r.source_label)
    else:
        f = _fact(r, booleans=plan.OPERATES_FIELDS)
    unit = r.unit if r.field_id in plan.ASSUMPTION_FIELDS else f.unit  # an assumption converts from its stated unit
    return replace(f, unit=unit, basis=r.basis, page=r.page)


def latest_plan(s, cid) -> m.Document | None:
    """P1: the company's transition plan with the latest as-of date; on a tie, the one uploaded last."""
    d = m.Document
    return s.scalars(
        select(d).where(d.company_id == cid, d.doc_type == DocType.TRANSITION_PLAN.value)
        .order_by(d.published_at.desc().nulls_last(), d.first_seen_at.desc()).limit(1)
    ).first()


def _latest_groups(rows, fields, latest: m.Document | None, anchor: str | None = None) -> list[list[Fact]]:
    """P2: list items grouped by basis; a group counts when its `anchor` fact's (any fact's, without one) primary
    citation is the latest plan."""
    groups: dict[str, list[view.CompanyFactRow]] = {}
    for r in rows:
        if r.field_id in fields:
            groups.setdefault(r.basis, []).append(r)
    return [[_plan_fact(r) for r in g] for g in groups.values()
            if latest and any(anchor in (None, r.field_id) and r.doc_id == latest.doc_id for r in g)]


def _plan_inputs(s, cid):
    """(action groups, target groups, phase-out groups from the latest plan, assumptions, operating facts,
    fact_id -> its document's as-of year, the latest plan's as-of year)."""
    rows = [r for fid in plan.FIELD_IDS for r in view.facts(s, cid, field_id=fid, limit=500) if r.status in _COUNTED]
    latest = latest_plan(s, cid)
    assumptions = [r for r in rows if r.field_id in plan.ASSUMPTION_FIELDS]
    years = {}
    for r in assumptions:  # shortcut: an uncited assumption converts at this year's rate; cite it to fix the year
        doc = get_document(s, r.doc_id) if r.doc_id else None
        years[r.fact_id] = (doc.published_at or doc.first_seen_at).year if doc else date.today().year
    return (
        _latest_groups(rows, plan.ACTION_FIELDS, latest, "ta_action_text"),
        _latest_groups(rows, plan.TARGET_FIELDS, latest),  # a target missing one field still shows (Incomplete target)
        _latest_groups(rows, plan.PHASEOUT_FIELDS, latest),
        [_plan_fact(r) for r in assumptions],
        [_plan_fact(r) for r in rows if r.field_id in plan.OPERATES_FIELDS],
        years,
        (latest.published_at or latest.first_seen_at).year if latest else None,
    )


def _cell_lookup(run_store) -> CellLookup:
    book = Ratings(run_store)

    def cell(code: str, region: str) -> Cell:
        c = book.cell(code, region)
        values = [v for v in c.result.values if v["counted"]] if c.result else []
        return Cell(getattr(c.rating, "value", c.rating), c.basis, c.evidence, values)

    return cell


@router.get("/companies/{ref}/transition", response_model=TransitionOut)
def get_company_transition(ref: str, run_store=Depends(get_run_store)) -> TransitionOut:
    b = load_benchmarks()
    rule_book, raw = load_rule_book(dataset.data_dir())
    versions = dict(benchmarks_version=b.version, rule_book_version=rule_book.version)
    with transaction() as s:
        cid = _resolve(s, ref)
        isic = s.get(m.Company, cid).isic_code
        sector = sector_for_isic(b, isic)
        if sector is None:
            reason = f"ISIC {isic} is not in a transition-barrier sector" if isic else "No ISIC code"
            return TransitionOut(in_scope=False, reason=reason, sector=None, capex=None, **versions)
        facts = _company_facts(s, cid)
        emissions = _company_facts(s, cid, _EMISSIONS)
        indicators = _company_facts(s, cid, _INDICATORS, _INDICATORS)
        groups, target_groups, phaseout_groups, assumptions, operates, years, plan_year = _plan_inputs(s, cid)
    capex = score_capex(facts, b.sectors[sector], b.licence_note)
    regions: dict[str, list[str]] = {}
    for score in dataset.load_scores():  # a criterion's regions: the cells the matrix has for it
        regions.setdefault(score.code, []).append(score.region.value)
    criteria = [(code, c.actions, regions.get(code, [])) for code, c in rule_book.criteria.items()]
    scored = score_plan(
        groups, assumptions, operates, criteria=criteria, cell=_cell_lookup(run_store), act_levers=b.act_levers,
        assumption_map=b.assumptions, conversions=raw["conversions"], doc_year=years.__getitem__,
    )
    delivery = {}
    if plan_year is not None:  # no latest plan: no target or phase-out counts
        targets, progress = score_targets(target_groups, emissions, plan_year)
        savings = {t.basis: f for g in groups
                   if (t := _first(g, "ta_action_text")) and (f := _first(g, "ta_action_ghg_saving"))}
        delivery = dict(targets=targets, target_progress=progress, coverage=score_coverage(targets, scored.actions, savings),
                        phaseouts=score_phaseouts(phaseout_groups, sector, plan_year))
    by_id = {f.fact_id: f for f in assumptions}
    for a in scored.assumptions:
        a.scenario = scenario_entries(a, by_id[a.fact_id], scored.regions, b.scenario_prices, raw["conversions"],
                                      years[a.fact_id])
    flags, flags_header = score_flags(
        reporting_year=capex.reporting_year, capex_facts=facts, redlines=capex.redlines,
        targets=delivery.get("targets", []), coverage=delivery.get("coverage"), phaseouts=delivery.get("phaseouts", []),
        actions=scored.actions, regions=scored.regions, operates=operates,
        net_zero=_indicator(indicators, _INDICATORS[0]), offsets=_indicator(indicators, _INDICATORS[1]),
    )
    return TransitionOut(in_scope=True, reason=None, sector=sector, capex=capex, **versions, **dict(scored), **delivery,
                         flags=flags, flags_header=flags_header)


@router.get("/transition-alignment/sectors/{sector}/companies", response_model=list[CompanyRef])
def get_sector_companies(sector: str, store=Depends(get_portfolio_store)) -> list[CompanyRef]:
    """R11: the in-scope portfolio companies of a sector, for a run of the presets via POST /api/extraction/start."""
    b = load_benchmarks()
    if sector not in b.sectors:
        raise HTTPException(404, f"Unknown sector: {sector}")
    return [c for c in store.list_companies() if sector_for_isic(b, c.isic_code) == sector]
