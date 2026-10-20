"""Plan delivery checks: target progress, abatement coverage, phase-out, scenario carbon price (spec 2026-10-20 §2-6).

Pure: no DB, no model. Groups are one target's or phase-out's counted facts each, already from the latest plan.
Arithmetic is Decimal; floats appear only in the response models.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from arp.schemas.transition_alignment import (
    ActionOut,
    AssumptionOut,
    CoverageActionOut,
    CoverageOut,
    PhaseoutOut,
    ScenarioOut,
    TargetOut,
    TargetProgressOut,
)
from arp.transition_alignment.actions import REGIONS, _first, converted_assumption
from arp.transition_alignment.benchmarks import REGION_GROUP, ScenarioGroup
from arp.transition_alignment.capex import Fact
from arp.transition_barrier.render import fmt_number

SECTOR_TIMELINES = {"Power & Utilities": 2040, "Shipping": 2040, "Heavy-Duty Road Transport": 2035}
SALE_NOTE = "Sale, not closure: ACT counts this negatively (GE p.139)"
_TONNES = {"tCO2e": Decimal(1), "MtCO2e": Decimal(1_000_000)}
_SAVING_TONNES = {"tCO2e/yr": Decimal(1), "MtCO2e/yr": Decimal(1_000_000)}
_MT = Decimal(1_000_000)
_CENT = Decimal("0.01")


def _r2(x: Decimal) -> Decimal:
    return x.quantize(_CENT, ROUND_HALF_UP)


def _num(f: Fact | None) -> Decimal | None:
    return f.value if f is not None and isinstance(f.value, Decimal) else None


def _int(f: Fact | None) -> int | None:
    return None if (v := _num(f)) is None else int(v)


def _ordered(groups: list[list[Fact]]) -> list[tuple[Fact, list[Fact]]]:
    """(anchor fact, group), by the anchor's page then fact_id; the anchor gives key and citation."""
    out = [(min(g, key=lambda f: f.fact_id), g) for g in groups if g]
    out.sort(key=lambda ag: (ag[0].page is None, ag[0].page or 0, ag[0].fact_id))
    return out


def _series(emissions: list[Fact]) -> dict[int, Decimal]:
    """E(year) = counted scope 1 + scope 2 in tCO2e, only for years with both."""
    by = {}
    for fid in ("tp_h_scope1_emissions", "tp_h_scope2_emissions"):
        for y in {f.year for f in emissions if f.field_id == fid and f.year is not None}:
            f = _first([e for e in emissions if e.year == y], fid)
            factor = _TONNES.get(f.unit or "tCO2e")
            if f.amount is not None and factor is not None:
                by.setdefault(y, {})[fid] = f.amount * factor
    return {y: v["tp_h_scope1_emissions"] + v["tp_h_scope2_emissions"] for y, v in by.items() if len(v) == 2}


def _target(group: list[Fact], anchor: Fact, e: dict[int, Decimal], ry: int | None, plan_year: int) -> TargetOut:
    get = {fid: _first(group, fid) for fid in {f.field_id for f in group}}.get
    scope = (f := get("ta_target_scope")) and f.value or None
    pct, year, base_year = _num(get("ta_target_pct")), _int(get("ta_target_year")), _int(get("ta_target_base_year"))
    base_f = get("ta_target_base_emissions")
    factor = _TONNES.get(base_f.unit or "") if base_f is not None else None
    base = base_f.amount * factor if base_f is not None and base_f.amount is not None and factor is not None else None
    set_year = _int(get("ta_target_set_year"))
    set_year = plan_year if set_year is None else set_year  # spec §3: the plan's as-of year when not stated
    kind = ratio = score = reason = gap = None
    if scope == "S1+2+3":
        reason = "Scope 3 target: progress not computed"
    elif scope != "S1+2" or pct is None or pct <= 0 or year is None or base_year is None:
        reason = "Incomplete target"  # pct <= 0 would make E_base - T zero (Review Focus 2)
    else:
        if ry is not None and ry - 10 <= year <= ry:
            kind = "past"
        elif ry is not None and set_year <= ry - 1 and year >= ry + 1:
            kind = "running"
        if base is not None and base > 0:
            gap = base * pct / 100  # E_base - T
        if gap is None:
            reason = "No base-year emissions"
        elif kind is None:
            reason = f"Target year {year} neither past nor running" if ry is not None else f"No emissions for {year}"
        elif kind == "past" and year not in e:
            reason = f"No emissions for {year}"
        else:
            if kind == "past":
                a = (base - e[year]) / gap
                s = Decimal(100) if a >= 1 else 100 * (2 * a - 1) if a > Decimal("0.5") else Decimal(0)
            else:
                a = (base - e[ry]) * (year - set_year) / (gap * (ry - set_year))  # a_RY / time
                s = min(max(a, Decimal(0)), Decimal(1)) * 100
            ratio, score = fmt_number(float(a)), float(_r2(s))
    out = TargetOut(
        key=anchor.basis, scope=scope, pct=None if pct is None else float(pct), year=year, base_year=base_year,
        base_emissions_shown=base_f.shown if base_f is not None else None, kind=kind, ratio=ratio, score=score,
        reason=reason, citation=anchor.citation, fact_ids=sorted(f.fact_id for f in group),
    )
    out._gap = gap
    return out


def score_targets(target_groups: list[list[Fact]], emissions: list[Fact], plan_year: int
                  ) -> tuple[list[TargetOut], TargetProgressOut | None]:
    """Each target's past/running score (ACT GE 1.4) and the 25/75 overall over scored targets."""
    e = _series(emissions)
    ry = max(e, default=None)
    targets = [_target(g, a, e, ry, plan_year) for a, g in _ordered(target_groups)]
    means = {}
    for kind in ("past", "running"):
        scores = [Decimal(str(t.score)) for t in targets if t.kind == kind and t.score is not None]
        if scores:
            means[kind] = sum(scores) / len(scores)
    if not means:
        return targets, None
    overall = _r2(Decimal("0.25") * means["past"] + Decimal("0.75") * means["running"] if len(means) == 2
                  else next(iter(means.values())))
    return targets, TargetProgressOut(score=float(overall), text=f"Target progress {fmt_number(float(overall))}% (ACT GE 1.4)")


def _coverage_action(a: ActionOut, saving: Fact | None, target_year: int) -> tuple[CoverageActionOut, Decimal | None]:
    shown = saving.shown if saving is not None else None
    factor = _SAVING_TONNES.get(saving.unit or "") if saving is not None else None
    tonnes = saving.amount * factor if saving is not None and saving.amount is not None and factor else None
    if saving is not None and saving.unit == "%":
        reason = "Saving in % not summed"
    elif tonnes is None:
        reason = "No quantified saving"
    elif a.year is None:
        reason = "No year"
    elif a.year > target_year:
        reason = "After the target year"
    else:
        return CoverageActionOut(key=a.key, saving_shown=shown, summed=True, reason=None), tonnes
    return CoverageActionOut(key=a.key, saving_shown=shown, summed=False, reason=reason), None


def score_coverage(targets: list[TargetOut], actions: list[ActionOut], saving_facts: dict[str, Fact]) -> CoverageOut:
    """Listed actions' savings vs the earliest running target's gap (ACT Core B02.c); `saving_facts` by action key."""
    running = [t for t in targets if t.kind == "running"]  # targets are in page order, so min keeps the earlier page
    if not running:
        return CoverageOut(target_key=None, percent=None, text=None, actions=[], reason="No running target")
    t = min(running, key=lambda t: t.year)
    if t._gap is None:
        return CoverageOut(target_key=t.key, percent=None, text=None, actions=[], reason="No base-year emissions")
    rows, covered = [], []
    for a in actions:
        row, tonnes = _coverage_action(a, saving_facts.get(a.key), t.year)
        rows.append(row)
        if tonnes is not None:
            covered.append(tonnes)
    if not covered:
        return CoverageOut(target_key=t.key, percent=None, text=None, actions=rows, reason="No summable action")
    total = sum(covered)
    pct = fmt_number(float(total / t._gap * 100))
    text = (f"Listed actions cover {pct}% of the {t.year} target gap "
            f"({fmt_number(float(total / _MT))} of {fmt_number(float(t._gap / _MT))} MtCO2e/yr)")
    return CoverageOut(target_key=t.key, percent=float(_r2(total / t._gap * 100)), text=text, actions=rows, reason=None)


def _share_points(share: Decimal) -> int:
    return 0 if share <= 25 else 25 if share <= 50 else 50 if share <= 75 else 75 if share <= 95 else 100


def _date_points(year: int, ry: int) -> int:
    d = year - ry
    return 100 if d <= 5 else 75 if d <= 10 else 50 if d <= 15 else 25 if d <= 20 else 0


def score_phaseouts(groups: list[list[Fact]], sector: str, plan_year: int) -> list[PhaseoutOut]:
    """Share (70%) and date (30%) points per phase-out (ACT GE 9.2 dim. 3), RY = the plan's as-of year; ACT Core D02.a."""
    timeline = SECTOR_TIMELINES.get(sector)
    out = []
    for anchor, g in _ordered(groups):
        get = {fid: _first(g, fid) for fid in {f.field_id for f in g}}.get
        share, year = _num(get("ta_phaseout_share_pct")), _int(get("ta_phaseout_year"))
        method = (f := get("ta_phaseout_method")) and f.value or None
        sp = None if share is None else _share_points(share)
        dp = None if year is None else _date_points(year, plan_year)
        reason = "No share stated" if sp is None else "No year stated" if dp is None else None
        score = None if reason else float(Decimal("0.7") * sp + Decimal("0.3") * dp)
        if timeline is None:
            timeline_text = "No ACT Core sector timeline"
        elif share is not None and share > 95 and year is not None and year <= timeline:
            timeline_text = f"Meets the ACT Core timeline ({timeline})"
        else:
            timeline_text = f"Does not meet the ACT Core timeline ({timeline})"
        out.append(PhaseoutOut(
            key=anchor.basis, activity=(f := get("ta_phaseout_activity")) and f.value or None,
            share=None if share is None else float(share), year=year, method=method, share_points=sp, date_points=dp,
            score=score, reason=reason, timeline_text=timeline_text, note=SALE_NOTE if method == "sale" else None,
            citation=anchor.citation, fact_ids=sorted(f.fact_id for f in g),
        ))
    return out


def _price(prices: dict[int, float], year: int) -> Decimal | None:
    """The table price, linear between table years; None outside the table."""
    pts = sorted((y, Decimal(str(p))) for y, p in prices.items())
    for (y0, p0), (y1, p1) in zip(pts, pts[1:], strict=False):
        if y0 <= year <= y1:
            return p0 + (p1 - p0) * (year - y0) / (y1 - y0)
    return pts[0][1] if len(pts) == 1 and pts[0][0] == year else None


def scenario_entries(assumption: AssumptionOut, fact: Fact, regions: list[str], groups: list[ScenarioGroup],
                     conversions: list[dict], doc_year: int) -> list[ScenarioOut]:
    """The IEA NZE price per region for a carbon-price assumption (ACT GE 5.3); `regions` are the operating regions."""
    if assumption.kind != "carbon_price":
        return []
    stated = fact.basis.removeprefix("region:")
    by_group = {g.group: g for g in groups}
    converted, shown, reason = converted_assumption(fact, "USD/tCO2", doc_year, conversions)
    out = []
    for region in [stated] if stated in REGIONS else regions if stated == "any" else []:
        group = by_group.get(REGION_GROUP[region])
        if group is None:  # shortcut: a benchmarks file without scenario prices gives no entry; spec is silent
            continue
        price = None if fact.year is None else _price(group.prices, fact.year)
        scenario = gap = None
        if reason is None and fact.year is None:
            reason_r = "No scenario price for (no year)"
        elif reason is None and price is None:
            reason_r = f"No scenario price for {fact.year}"
        else:
            reason_r = reason
        if reason_r is None:
            scenario = f"{fmt_number(float(price))} USD/tCO2 (IEA NZE {fact.year}, {group.group})"
            d = _r2(Decimal(str(converted)) - price)
            gap = "0 USD/tCO2" if d == 0 else ("+" if d > 0 else "-") + f"{fmt_number(float(abs(d)))} USD/tCO2"
        out.append(ScenarioOut(region=region, year=fact.year, scenario=scenario, assumption=shown, gap=gap,
                               reason=reason_r))
    return out
