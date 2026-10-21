"""Consistency flags: five ACT narrative questions answered in code (spec 2026-10-21 sections 1-2). Pure: no DB, no model.

Each flag is `raised`, `clear` or `not checked`; flags never combine into a score.
"""

from __future__ import annotations

from decimal import Decimal

from arp.presets.transition_plan_actions import OPERATES_FIELDS
from arp.schemas.transition_alignment import ActionOut, CoverageOut, FlagOut, PhaseoutOut, RedlineOut, TargetOut
from arp.transition_alignment.actions import REGIONS, _first
from arp.transition_alignment.capex import Fact
from arp.transition_barrier.render import fmt_number

_FLAGS = {  # id: (title, cite), in response order
    "no_lowcarbon_capex": ("Falling emissions claimed, no low-carbon capex", "ACT Framework p.64"),
    "net_zero_no_phaseout": ("Net zero without phase-out", "ACT Framework pp.61–62"),
    "expansion_vs_net_zero": ("Expansion against net zero", "ACT Framework p.62"),
    "regions_left_out": ("Regions left out", "ACT Framework p.61"),
    "offsets_emphasised": ("Offsets emphasised", "ACT Framework p.62; ACT Core p.26"),
}
CLEAR = "No flag."
NO_NET_ZERO = "No net-zero answer"
_LOWCARBON = ("tc_lowcarbon_capex", "tc_lowcarbon_capex_share_pct")
_MT = Decimal(1_000_000)


def _yes_no(f: Fact | None) -> bool | None:
    """F1: only a real Yes/No counts; anything else reads as no answer."""
    return f.value if f is not None and isinstance(f.value, bool) else None


def _capex_flag(ry: int | None, capex_facts: list[Fact], targets: list[TargetOut], coverage: CoverageOut | None):
    running = [t for t in targets if t.kind == "running"]
    if not running:
        return "clear", CLEAR, []
    t = min(running, key=lambda t: t.year)  # the earliest running target, as coverage picks it
    if ry is None:
        return "not checked", "No capex reporting year", []
    if any(f.field_id in _LOWCARBON and f.year == ry and f.amount is not None and f.amount > 0 for f in capex_facts):
        return "clear", CLEAR, t.fact_ids
    text = f"{t.year} target −{fmt_number(t.pct)}%"
    if coverage is not None and coverage._covered is not None:  # set only when coverage summed an action
        text += f" and actions saving {fmt_number(float(coverage._covered / _MT))} MtCO2e/yr"
    return "raised", f"{text}, but no low-carbon capex disclosed for {ry}.", t.fact_ids


def _phaseout_flag(net_zero: Fact | None, phaseouts: list[PhaseoutOut]):
    nz = _yes_no(net_zero)
    if nz is None:
        return "not checked", NO_NET_ZERO, []
    if nz and not phaseouts:
        return "raised", "Net-zero target reported, but no phase-out commitment disclosed.", [net_zero.fact_id]
    return "clear", CLEAR, [net_zero.fact_id]


def _expansion_flag(net_zero: Fact | None, redlines: list[RedlineOut]):
    nz = _yes_no(net_zero)
    if nz is None:
        return "not checked", NO_NET_ZERO, []
    breached = [r for r in redlines if r.status == "breached"]
    ids = [net_zero.fact_id] + sorted(r.fact_id for r in breached)
    if not nz:
        return "clear", CLEAR, ids
    if not redlines:
        return "not checked", "No redline for this sector", []
    if breached:
        return "raised", f"Net-zero target reported, but redline breached: {'; '.join(r.label for r in breached)}.", ids
    if any(r.status == "no disclosure" for r in redlines):
        return "not checked", "No redline disclosure", []
    return "clear", CLEAR, ids


def _regions_flag(regions: list[str], actions: list[ActionOut], operates: list[Fact]):
    if len(regions) < 2:
        return "not checked", "Fewer than two operating regions", []
    covered = set()
    for a in actions:  # as phase 2 matches: its own region, else every operating region; `other` -> none
        covered.update([a.region] if a.region in REGIONS else [] if a.region else regions)
    left = [r for r in regions if r not in covered]
    ids = [f.fact_id for fid in OPERATES_FIELDS if (f := _first(operates, fid)) is not None]
    if left and len(left) < len(regions):
        return "raised", f"Operates in {' and '.join(left)}, but no listed action covers {'it' if len(left) == 1 else 'them'}.", ids
    return "clear", CLEAR, ids


def _offsets_flag(offsets: Fact | None):
    v = _yes_no(offsets)
    if v is None:
        return "not checked", "No offsets answer", []
    if v:
        return "clear", CLEAR, [offsets.fact_id]
    return "raised", "Does not state that credits are used only for residual emissions.", [offsets.fact_id]


def score_flags(
    *, reporting_year: int | None, capex_facts: list[Fact], redlines: list[RedlineOut], targets: list[TargetOut],
    coverage: CoverageOut | None, phaseouts: list[PhaseoutOut], actions: list[ActionOut], regions: list[str],
    operates: list[Fact], net_zero: Fact | None, offsets: Fact | None,
) -> tuple[list[FlagOut], str]:
    """(the five flags in order, the header line). `reporting_year` is phase 1's capex RY (F2); `redlines` phase 1's,
    one per sector redline; `net_zero` / `offsets` the counted `A_ambition_3` / `A_offsetting_13` facts."""
    results = {
        "no_lowcarbon_capex": _capex_flag(reporting_year, capex_facts, targets, coverage),
        "net_zero_no_phaseout": _phaseout_flag(net_zero, phaseouts),
        "expansion_vs_net_zero": _expansion_flag(net_zero, redlines),
        "regions_left_out": _regions_flag(regions, actions, operates),
        "offsets_emphasised": _offsets_flag(offsets),
    }
    flags = [FlagOut(id=fid, title=_FLAGS[fid][0], state=state, text=text, cite=_FLAGS[fid][1], fact_ids=ids)
             for fid, (state, text, ids) in results.items()]
    n = sum(f.state == "raised" for f in flags)
    return flags, f"Consistency: {n} of 5 checks raise a flag" if n else "Consistency: no check raises a flag"
