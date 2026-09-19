"""Firm-level Kaya decomposition, and what counts as a carbon reduction.

A change in a firm's Scope 1+2 emissions is not the same thing as that firm
abating. Six drivers move the number and only some are the firm acting:

    Scope 1 = output x energy intensity x fuel mix
    Scope 2 = output x electricity intensity x grid emission factor

Energy intensity, fuel mix and electricity intensity are management. Output is
the business cycle. The grid factor is someone else's decarbonisation. A firm
in a cleaning grid shows falling *location-based* Scope 2 while managing
nothing, which is why location-based reporting, though better than market-based
for this purpose, is still not a measure of firm behaviour.

Worked example. Two firms both post roughly a 20% reduction:

    Firm A   headline -22.0%   attributable -22.0%   passive   0.0%
    Firm B   headline -19.9%   attributable   0.0%   passive -19.9%

Firm B shrank 15% and sat in a grid that cleaned up 5%. A label built on
headline change treats these as the same firm, and any model trained on it
learns to identify firms in clean grids having bad years.

This module decomposes the change with the same log-mean Divisia machinery as
`attribution.py`, and splits the result into a firm-attributable part and a
passive part. Both are exactly additive; the tests assert it.

One useful side effect. Reported Scope 2 and the electricity-times-grid
product are two independent measurements of the same quantity, so their
difference is carried as `data_gap` rather than charged to a driver. That makes
the gap a detector for market-based reporting: a firm that books a procurement
reduction while drawing the same power from the same grid shows its entire
reduction in the gap, credited to nothing. It is the review's central argument,
procurement against abatement, falling out of the arithmetic at firm level.

Most firms do not disclose physical output or energy, so the decomposition
degrades through three tiers and records which one it used. The tier is part of
the result, not an implementation detail: tier 2 and tier 3 estimates are not
comparable to tier 1 and should never be pooled without a control.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from arp.decarb.schemas import EmissionsBasis, FirmYear, Panel
from arp.decarb.stats import log_mean

__all__ = [
    "Tier",
    "tier_contamination",
    "tier_coverage",
    "KayaResult",
    "available_tier",
    "decompose_firm",
    "attributable_labels",
]


class Tier(str, Enum):
    """How cleanly firm action can be separated, given the disclosed data."""

    FULL_KAYA = "tier1_full_kaya"
    CONSTANT_GRID = "tier2_constant_grid"
    CHAINED = "tier3_chained"

    @property
    def rank(self) -> int:
        return {"tier1_full_kaya": 1, "tier2_constant_grid": 2, "tier3_chained": 3}[self.value]

    def describe(self) -> str:
        return {
            Tier.FULL_KAYA: (
                "Output, energy and grid all observed: output and grid effects are removed, "
                "leaving energy intensity, fuel mix and electricity intensity."
            ),
            Tier.CONSTANT_GRID: (
                "Electricity volume and grid factor observed but physical output is not: the "
                "grid effect is removed, output remains confounded in the residual."
            ),
            Tier.CHAINED: (
                "Only emissions observed: constant-perimeter change with no driver separation. "
                "Passive change is not removed and the label is contaminated accordingly."
            ),
        }[self]


@dataclass(slots=True)
class KayaResult:
    """Additive decomposition of one firm's Scope 1+2 change over one step.

    Components are in emissions units. `None` marks a term the tier could not
    identify, which is different from a term that was zero.
    """

    firm_id: str
    start_year: int
    end_year: int
    tier: Tier
    start_emissions: float
    end_emissions: float
    output: float | None = None
    energy_intensity: float | None = None
    fuel_mix: float | None = None
    electricity_intensity: float | None = None
    grid: float | None = None
    # Firm-side change the tier could not decompose. At tier 2 this is the
    # Scope 1 change, which is management but still carries output; at tier 3
    # it is the whole change. Counted as attributable, because the alternative
    # is silently crediting it to nobody.
    unexplained: float = 0.0
    # Reported minus reconstructed emissions: rounding or a boundary change.
    # Never attributed to a driver. Large values mean the activity data and
    # the emissions data disagree and the firm should be inspected.
    data_gap: float = 0.0

    @property
    def total_change(self) -> float:
        return self.end_emissions - self.start_emissions

    @property
    def attributable(self) -> float:
        """Change the firm can be credited with: efficiency, fuel and power use."""
        named = sum(
            v for v in (self.energy_intensity, self.fuel_mix, self.electricity_intensity) if v is not None
        )
        return named + self.unexplained

    @property
    def passive(self) -> float:
        """Change from output and from the grid cleaning up."""
        return sum(v for v in (self.output, self.grid) if v is not None)

    @property
    def residual(self) -> float:
        """Should be ~0 at every tier. Non-zero means the identity broke."""
        return self.total_change - (self.attributable + self.passive + self.data_gap)

    def as_rate(self, value: float) -> float:
        """Express a component as a fraction of starting emissions."""
        if self.start_emissions <= 0:
            return float("nan")
        return value / self.start_emissions

    @property
    def attributable_rate(self) -> float:
        return self.as_rate(self.attributable)

    def explain(self) -> str:
        parts = [f"{self.firm_id} {self.start_year}->{self.end_year} [{self.tier.value}]"]
        parts.append(f"  headline      {self.as_rate(self.total_change):+7.1%}")
        parts.append(f"  attributable  {self.attributable_rate:+7.1%}")
        parts.append(f"  passive       {self.as_rate(self.passive):+7.1%}")
        if abs(self.data_gap) > 1e-9:
            parts.append(f"  data gap      {self.as_rate(self.data_gap):+7.1%}")
        for name, val in (
            ("output", self.output),
            ("energy_intensity", self.energy_intensity),
            ("fuel_mix", self.fuel_mix),
            ("electricity_intensity", self.electricity_intensity),
            ("grid", self.grid),
        ):
            if val is not None:
                parts.append(f"    {name:<22}{self.as_rate(val):+7.1%}")
        return "\n".join(parts)


def _positive(*vals) -> bool:
    return all(v is not None and v > 0 for v in vals)


def available_tier(before: FirmYear, after: FirmYear) -> Tier:
    """Best tier the two observations support.

    Tier 1 needs output, own-combustion energy, electricity and a grid factor
    in both years. Tier 2 drops output but keeps electricity and grid. Tier 3
    is the fallback and separates nothing.
    """
    if _positive(
        before.output, after.output, before.fuel_energy, after.fuel_energy,
        before.electricity_mwh, after.electricity_mwh, before.grid_factor, after.grid_factor,
        before.scope1, after.scope1,
    ):
        return Tier.FULL_KAYA
    if _positive(
        before.electricity_mwh, after.electricity_mwh, before.grid_factor, after.grid_factor,
    ):
        return Tier.CONSTANT_GRID
    return Tier.CHAINED


def decompose_firm(before: FirmYear, after: FirmYear, *, tier: Tier | None = None) -> KayaResult:
    """Decompose one firm's Scope 1+2 change between two observations.

    `tier` forces a tier; by default the best supported one is used. Forcing a
    lower tier on data that supports a higher one is useful for measuring how
    much contamination the lower tier leaves in.
    """
    if before.firm_id != after.firm_id:
        raise ValueError("decompose_firm needs two observations of the same firm")
    if after.year <= before.year:
        raise ValueError("after must follow before")

    tier = tier or available_tier(before, after)
    s0, s1 = before.scope12, after.scope12
    if s0 is None or s1 is None or s0 <= 0 or s1 <= 0:
        raise ValueError(f"{before.firm_id}: Scope 1+2 must be positive in both years")

    result = KayaResult(
        firm_id=before.firm_id,
        start_year=before.year,
        end_year=after.year,
        tier=tier,
        start_emissions=s0,
        end_emissions=s1,
    )

    if tier is Tier.CHAINED:
        # Nothing separable. The whole change goes to `unexplained` and so
        # counts as attributable. That is not a claim that the firm did it;
        # the tier is on the result and says the label is contaminated.
        result.unexplained = s1 - s0
        return result

    # Scope 2 splits the same way at both remaining tiers.
    e0 = before.electricity_mwh * before.grid_factor
    e1 = after.electricity_mwh * after.grid_factor
    if e0 <= 0 or e1 <= 0:
        raise ValueError(f"{before.firm_id}: derived Scope 2 must be positive")
    w2 = log_mean(e1, e0)
    grid_term = w2 * math.log(after.grid_factor / before.grid_factor)

    if tier is Tier.CONSTANT_GRID:
        # Electricity volume is firm behaviour, though it still carries output.
        # Scope 1 cannot be split without energy data, so it and any gap
        # between reported and derived Scope 2 fall into `unexplained`, which
        # counts as attributable. This is the tier's known limitation: output
        # is not removed, only the grid is.
        elec_term = w2 * math.log(after.electricity_mwh / before.electricity_mwh)
        result.grid = grid_term
        result.electricity_intensity = elec_term
        result.unexplained = (s1 - s0) - (elec_term + grid_term)
        return result

    # Tier 1: full decomposition.
    ei0 = before.fuel_energy / before.output
    ei1 = after.fuel_energy / after.output
    fm0 = before.scope1 / before.fuel_energy
    fm1 = after.scope1 / after.fuel_energy
    xi0 = before.electricity_mwh / before.output
    xi1 = after.electricity_mwh / after.output

    w1 = log_mean(after.scope1, before.scope1)
    out_ratio = math.log(after.output / before.output)

    result.output = w1 * out_ratio + w2 * out_ratio
    result.energy_intensity = w1 * math.log(ei1 / ei0)
    result.fuel_mix = w1 * math.log(fm1 / fm0)
    result.electricity_intensity = w2 * math.log(xi1 / xi0)
    result.grid = grid_term
    # Reported Scope 1+2 can differ from output x intensity x factor because of
    # rounding or a boundary change. Carry the gap explicitly rather than
    # letting it distort a driver.
    covered = result.output + result.energy_intensity + result.fuel_mix + result.electricity_intensity + result.grid
    result.data_gap = (s1 - s0) - covered
    return result


def attributable_labels(
    panel: Panel,
    *,
    start_year: int,
    end_year: int,
    disclosed_only: bool = True,
    exclude_restated: bool = True,
    threshold: float = 0.0,
    min_tier: Tier | None = None,
) -> dict[str, tuple[float, bool, Tier]]:
    """Firm-attributable annualised decarbonisation rate over a window.

    Returns {firm_id: (annualised_attributable_rate, is_decarboniser, tier)}.

    The rate is the attributable component expressed as a fraction of starting
    emissions and annualised over the window, so it is comparable with the
    headline rates `labels.decarboniser_labels` produces. Comparing the two is
    the point: an indicator that predicts the headline but not this one is
    identifying firms in cleaning grids or shrinking markets.

    `exclude_restated` drops firms flagged as having restated their base year,
    since a restatement makes the two observations non-comparable and no
    decomposition can repair that.

    `min_tier` refuses firms whose data only supports a weaker tier. Leaving it
    None keeps everything and records the tier per firm, which is usually
    better: tier is then available as a control rather than a silent filter.
    """
    start = panel.by_year(start_year)
    end = panel.by_year(end_year)
    span = end_year - start_year
    if span <= 0:
        raise ValueError("end_year must follow start_year")

    out: dict[str, tuple[float, bool, Tier]] = {}
    for firm_id in sorted(set(start) & set(end)):
        a, b = start[firm_id], end[firm_id]
        if disclosed_only and (a.basis is not EmissionsBasis.REPORTED or b.basis is not EmissionsBasis.REPORTED):
            continue
        if exclude_restated and (a.restated or b.restated):
            continue
        tier = available_tier(a, b)
        if min_tier is not None and tier.rank > min_tier.rank:
            continue
        try:
            res = decompose_firm(a, b, tier=tier)
        except ValueError:
            continue
        rate = res.attributable_rate
        if math.isnan(rate) or rate <= -1.0:
            continue
        annualised = (1.0 + rate) ** (1.0 / span) - 1.0
        out[firm_id] = (annualised, annualised < threshold, tier)
    return out


def tier_coverage(panel: Panel, start_year: int, end_year: int) -> dict[str, int]:
    """How many firms each tier is available for.

    Report this. Tier availability is correlated with firm quality and sector,
    so a tier-1 sample is selected and any result from it generalises to the
    kind of firm that discloses physical output, not to the universe.
    """
    start, end = panel.by_year(start_year), panel.by_year(end_year)
    counts = {t.value: 0 for t in Tier}
    for firm_id in sorted(set(start) & set(end)):
        counts[available_tier(start[firm_id], end[firm_id]).value] += 1
    return counts


def tier_contamination(panel: Panel, start_year: int, end_year: int) -> dict[str, dict[str, float]]:
    """How much a weaker tier over-credits, measured on firms that support tier 1.

    For every firm with full activity data, compute the attributable rate at
    tier 1 and at each weaker tier, and report the mean gap. Tier 2 leaves
    output in, so a firm that shrank is credited with abating; tier 3 leaves
    output and the grid in.

    This is the calibration a mixed-tier study needs. A tier-2 sample is not
    wrong, it is biased by a knowable amount, and that amount can be estimated
    on the tier-1 subsample and carried as a correction or at least reported.

    Returns per tier: mean and mean absolute gap against tier 1, plus n. Note
    the tier-1 subsample is itself selected toward firms that disclose physical
    output, so the correction generalises only as far as that selection does.

    **Read the absolute gap, not the signed one.** Tier 3 leaves both the
    output and grid effects in, and while grids are cleaning those two biases
    point in opposite directions and partly cancel. On the calibrated panel
    tier 3's signed gap is smaller than tier 2's while its absolute gap is the
    same, so a signed comparison makes the worst tier look like the better one.
    """
    start, end = panel.by_year(start_year), panel.by_year(end_year)
    gaps: dict[str, list[float]] = {Tier.CONSTANT_GRID.value: [], Tier.CHAINED.value: []}
    for firm_id in sorted(set(start) & set(end)):
        a, b = start[firm_id], end[firm_id]
        if available_tier(a, b) is not Tier.FULL_KAYA:
            continue
        try:
            truth = decompose_firm(a, b, tier=Tier.FULL_KAYA).attributable_rate
        except ValueError:
            continue
        for weak in (Tier.CONSTANT_GRID, Tier.CHAINED):
            try:
                est = decompose_firm(a, b, tier=weak).attributable_rate
            except ValueError:
                continue
            if math.isnan(truth) or math.isnan(est):
                continue
            gaps[weak.value].append(est - truth)
    out: dict[str, dict[str, float]] = {}
    for tier_name, vals in gaps.items():
        if not vals:
            continue
        out[tier_name] = {
            "n": len(vals),
            "mean_gap": math.fsum(vals) / len(vals),
            "mean_abs_gap": math.fsum(abs(v) for v in vals) / len(vals),
        }
    return out
