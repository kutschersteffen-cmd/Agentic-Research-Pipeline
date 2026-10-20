"""Plan actions: operating regions, barrier match, assumptions vs evidence and B02 (spec sections 4-5). Pure: no DB.

The match only reads barrier cells through `cell`; it never derives, ratifies or writes barrier data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from arp.presets.transition_plan_actions import OPERATES_FIELDS
from arp.schemas.transition_alignment import (
    ActionOut,
    ActLeverOut,
    AssumptionOut,
    B02Out,
    BarrierOut,
    ComparisonOut,
    PlanOut,
)
from arp.transition_alignment.benchmarks import Source, citation
from arp.transition_alignment.capex import Fact
from arp.transition_barrier.render import fmt_number
from arp.transition_barrier.units import convert

REGIONS = ("European Union", "United States", "China")
NO_REGION = "No operating region disclosed"
_OPERATES = dict(zip(OPERATES_FIELDS, REGIONS, strict=True))
_ORDER = {r: i for i, r in enumerate(REGIONS)}


@dataclass(frozen=True)
class Cell:
    """A barrier cell's current rating (P9: an unrated cell is None, None, "", [])."""

    rating: str | None
    basis: str | None  # derived | hand_rated
    evidence: str
    values: list[dict]  # counted values of the current result: fact, value, unit, document, page, document_id, url


CellLookup = Callable[[str, str], Cell]
Criteria = list[tuple[str, list[str], list[str]]]  # (code, action ids, regions), rule-book order


def _first(facts: list[Fact], field_id: str) -> Fact | None:
    """The counted fact of a field: the lowest fact_id (as phase 1)."""
    return min((f for f in facts if f.field_id == field_id), key=lambda f: f.fact_id, default=None)


def operating_regions(facts: list[Fact]) -> list[str]:
    """Regions whose `ta_operates_*` fact counts as Yes, in region order."""
    return [r for fid, r in _OPERATES.items() if (f := _first(facts, fid)) is not None and f.value is True]


def _ids(*facts: Fact | None) -> list[int]:
    return [f.fact_id for f in facts if f is not None]


def _b02b(status: str | None, year: int | None) -> B02Out:
    if status == "implemented":
        return B02Out(met=True, text=f"implemented ({year})" if year is not None else "implemented")
    if status != "planned" or year is None:  # no counted status: neither implemented nor planned
        return B02Out(met=False, text="No timeframe: ignored")
    return B02Out(met=True, text=f"near term ({year})" if year <= 2030 else f"long term ({year})")


def _b02d(needed: Fact | None, allocated: Fact | None) -> B02Out:
    ids = _ids(needed, allocated)
    if needed and allocated:
        if needed.unit != allocated.unit:
            return B02Out(met=False, text="Needed and allocated in different currencies", fact_ids=ids)
        return B02Out(met=True, text=f"{needed.shown} needed, {allocated.shown} allocated", fact_ids=ids)
    if needed or allocated:
        return B02Out(met=False, text="No split of funds needed and allocated", fact_ids=ids)
    return B02Out(met=False, text="No funding stated")


def _sorted_by_region(items: list) -> list:
    """Barrier entries and comparisons: by region, then criterion code."""
    return sorted(items, key=lambda x: (_ORDER[x.region], x.code))


def _action(group: list[Fact], text: Fact, ops: list[str], criteria: Criteria, cell: CellLookup, act_levers: dict):
    """(ActionOut, the regions it is matched in)."""
    get = {fid: _first(group, fid) for fid in {f.field_id for f in group}}.get
    action_id = (f := get("ta_action_id")) and f.value
    status = (f := get("ta_action_status")) and f.value
    year = int(f.value) if (f := get("ta_action_year")) is not None and f.value is not None else None
    region = (f := get("ta_action_region")) and f.value
    regions = [region] if region in REGIONS else [] if region else ops
    note = NO_REGION if not region and not ops else None
    entries = []
    for code, ids, crit_regions in criteria:
        if action_id in ids:
            for r in regions:
                if r in crit_regions:
                    c = cell(code, r)
                    entries.append(BarrierOut(code=code, region=r, rating=c.rating, basis=c.basis, evidence=c.evidence,
                                              values=c.values))
    lever = act_levers.get(action_id) if action_id else None
    saving = get("ta_action_ghg_saving")
    b = _b02b(status, year).model_copy(update={"fact_ids": _ids(get("ta_action_status"), get("ta_action_year"))})
    out = ActionOut(
        key=text.basis, action_id=action_id or None,
        act_lever=lever and ActLeverOut(wording=lever["wording"], citation=citation(Source(**lever["source"]))),
        text=str(text.value), status=status or None, year=year, region=region or None, citation=text.citation,
        timeframe=b.text if b.met else None,
        b02={
            "b": b,
            "c": B02Out(met=True, text=saving.shown, fact_ids=[saving.fact_id]) if saving
            else B02Out(met=False, text="No quantified GHG saving"),
            "d": _b02d(get("ta_action_capex_needed"), get("ta_action_capex_allocated")),
        },
        barriers=_sorted_by_region(entries), note=note, fact_ids=sorted(f.fact_id for f in group),
    )
    return out, regions


def _evidence(c: Cell, fact: str) -> tuple[str, list[dict]]:
    if c.basis == "hand_rated":
        return f"hand-rated, no figure: {c.evidence}", []
    values = [v for v in c.values if v.get("fact") == fact]
    if not values:
        return "no counted value", []
    return ", ".join(f"{_with_unit(v['value'], v['unit'])} ({v['document']}, p. {v['page']})" for v in values), values


def _with_unit(x: float, unit: str | None) -> str:
    return f"{fmt_number(x)} {unit}" if unit else fmt_number(x)


def _assumption(f: Fact, matched: dict[str, set[str]], criteria: Criteria, cell: CellLookup, assumption_map: dict,
                conversions: list[dict], doc_year: Callable[[int], int]) -> AssumptionOut:
    kind = f.field_id.removeprefix("ta_assumed_")
    stated = f.basis.removeprefix("region:")
    region = stated if stated in REGIONS else None
    spec = assumption_map.get(kind)
    target = spec.unit if spec else f.unit
    if f.value is None:
        converted, reason = None, "No value"
    else:
        converted, reason = convert(float(f.value), f.unit or "", target, doc_year(f.fact_id), conversions)
    shown = None if converted is None else _with_unit(converted, target) + ("" if f.unit == target else f" ({f.shown})")
    by_code = {code: ids for code, ids, _ in criteria}
    out = []
    for ref in spec.barrier_facts if spec else []:
        code, _, bfact = ref.partition(".")
        regions = set().union(*(matched.get(a, set()) for a in by_code.get(code, [])))
        crit_regions = next((r for c, _, r in criteria if c == code), [])
        for r in regions & set(crit_regions) & ({region} if region else set(REGIONS)):
            evidence, values = _evidence(cell(code, r), bfact)
            gap = None
            if converted is not None and len(values) == 1:
                d = converted - float(values[0]["value"])
                gap = ("+" if d >= 0 else "-") + _with_unit(abs(d), target)
            out.append(ComparisonOut(code=code, region=r, assumption=shown, evidence=evidence, gap=gap, reason=reason))
    return AssumptionOut(kind=kind, region=region, year=f.year, citation=f.citation, fact_id=f.fact_id,
                         comparisons=_sorted_by_region(out))


def score_plan(
    action_groups: list[list[Fact]], assumptions: list[Fact], operates: list[Fact], *, criteria: Criteria,
    cell: CellLookup, act_levers: dict, assumption_map: dict, conversions: list[dict], doc_year: Callable[[int], int],
) -> PlanOut:
    """Groups are one action's counted facts each (already from the latest plan); a group without text is not listed.

    `assumption_map` is the benchmarks' `assumptions` (kind -> unit, barrier_facts); `doc_year(fact_id)` is the
    as-of year of the fact's document, for the conversion rate.
    """
    ops = operating_regions(operates)
    texts = [(t, g) for g in action_groups if (t := _first(g, "ta_action_text")) is not None]
    texts.sort(key=lambda tg: (tg[0].page is None, tg[0].page or 0, tg[0].fact_id))  # P2: page, then fact_id
    actions, matched = [], {}
    for text, group in texts:
        a, regions = _action(group, text, ops, criteria, cell, act_levers)
        actions.append(a)
        if a.action_id:
            matched.setdefault(a.action_id, set()).update(regions)
    implemented = sum(a.status == "implemented" for a in actions)
    planned = sum(a.status == "planned" and a.b02["b"].met for a in actions)
    counts = f"{implemented} implemented, {planned} planned with a timeframe"
    b02a = None
    if actions:
        met = implemented >= 3 and planned >= 1
        b02a = B02Out(met=met, text=f"met: {counts}" if met else f"not met: {counts} (needs 3 and 1)")
    return PlanOut(
        regions=ops, actions=actions, b02a=b02a,
        assumptions=[_assumption(f, matched, criteria, cell, assumption_map, conversions, doc_year) for f in assumptions],
    )
