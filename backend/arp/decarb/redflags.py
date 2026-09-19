"""Greenwashing red-flag profiles.

Analysis of a greenwashing red-flag profile, and the constraint Brown, Hsu &
Manya's (2026) results place on how such a profile may be used.

The flags themselves are built by `arp.decarb.flags`, which implements their
coding rules against Net Zero Tracker, CDP and LobbyMap fields. This module
takes the resulting booleans and asks what can be done with them.

They find 96% of pledging companies exhibit at least one red flag, and that
the flags are only weakly correlated with each other. Several pairwise phi
correlations are negative: target ambition against lack of Scope 3 coverage
is -0.19, and against offset reliance -0.18. Being off-track correlates with
almost nothing.

That means greenwashing is not one latent trait. A firm with an ambitious
target and heavy offset reliance and a firm with a narrow target and no
offsets both score "2" on a summed index and are not the same object.
`profile_is_multidimensional` tests this on the user's own panel so the
decision to sum or not is evidence-based rather than assumed.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from arp.decarb.schemas import RED_FLAGS, Panel
from arp.decarb.stats import phi_coefficient

__all__ = [
    "from_assessments",
    "FlagPrevalence",
    "CompositeVerdict",
    "prevalence",
    "correlation_matrix",
    "co_occurrence",
    "profile_is_multidimensional",
    "profile_counts",
    "compare_to_published_prevalence",
]


@dataclass(slots=True)
class FlagPrevalence:
    flag: str
    observed: float
    published: float | None
    n: int

    @property
    def delta(self) -> float | None:
        if self.published is None:
            return None
        return self.observed - self.published


@dataclass(slots=True)
class CompositeVerdict:
    """Whether summing the flags into one score is defensible on this panel."""

    mean_abs_phi: float
    max_abs_phi: float
    n_negative_pairs: int
    n_pairs: int
    composite_defensible: bool

    def explain(self) -> str:
        if self.composite_defensible:
            return (
                f"Mean |phi| = {self.mean_abs_phi:.3f} across {self.n_pairs} pairs. The flags "
                "co-move enough on this panel that a summed score retains most of the signal."
            )
        return (
            f"Mean |phi| = {self.mean_abs_phi:.3f} across {self.n_pairs} pairs, "
            f"{self.n_negative_pairs} of them negative. The flags are close to orthogonal, so a "
            "summed score collapses distinct failure modes into one number. Model the profile "
            "jointly instead (Brown, Hsu & Manya 2026)."
        )


def _rows_with_flags(panel: Panel, year: int | None) -> list:
    rows = [r for r in panel.rows if r.red_flags]
    if year is not None:
        rows = [r for r in rows if r.year == year]
    return rows


def prevalence(panel: Panel, *, year: int | None = None) -> list[FlagPrevalence]:
    """Observed prevalence of each flag, next to the published benchmark."""
    rows = _rows_with_flags(panel, year)
    out: list[FlagPrevalence] = []
    for flag in RED_FLAGS:
        present = [r for r in rows if flag in r.red_flags]
        if not present:
            continue
        hits = sum(1 for r in present if r.red_flags[flag])
        out.append(FlagPrevalence(flag, hits / len(present), RED_FLAGS[flag], len(present)))
    return sorted(out, key=lambda f: -f.observed)


def compare_to_published_prevalence(panel: Panel, *, year: int | None = None, tolerance: float = 0.15) -> list[str]:
    """Flags whose prevalence departs materially from the published figures.

    A large gap is not necessarily an error, but it means the panel is not
    the population Brown, Hsu & Manya studied and their correlation results
    should not be assumed to carry over.
    """
    warnings: list[str] = []
    for fp in prevalence(panel, year=year):
        if fp.delta is not None and abs(fp.delta) > tolerance:
            warnings.append(
                f"{fp.flag}: observed {fp.observed:.0%} against published {fp.published:.0%} "
                f"(delta {fp.delta:+.0%}, n={fp.n})"
            )
    return warnings


def correlation_matrix(panel: Panel, *, year: int | None = None) -> dict[tuple[str, str], float]:
    """Pairwise phi correlations between red flags."""
    rows = _rows_with_flags(panel, year)
    flags = [f for f in RED_FLAGS if any(f in r.red_flags for r in rows)]
    out: dict[tuple[str, str], float] = {}
    for i, a in enumerate(flags):
        for b in flags[i + 1 :]:
            paired = [(r.red_flags[a], r.red_flags[b]) for r in rows if a in r.red_flags and b in r.red_flags]
            if len(paired) < 2:
                continue
            out[(a, b)] = phi_coefficient([p[0] for p in paired], [p[1] for p in paired])
    return out


def co_occurrence(panel: Panel, *, year: int | None = None) -> dict[tuple[str, str], int]:
    """Raw counts of firms carrying each pair of flags."""
    rows = _rows_with_flags(panel, year)
    flags = list(RED_FLAGS)
    out: dict[tuple[str, str], int] = {}
    for i, a in enumerate(flags):
        for b in flags[i + 1 :]:
            out[(a, b)] = sum(1 for r in rows if r.red_flags.get(a) and r.red_flags.get(b))
    return out


def profile_counts(panel: Panel, *, year: int | None = None) -> Counter:
    """Distribution of the number of flags carried per firm.

    Brown, Hsu & Manya report 96% with at least one, 41% with exactly one,
    and 12% with four or more.
    """
    rows = _rows_with_flags(panel, year)
    return Counter(sum(1 for v in r.red_flags.values() if v) for r in rows)


def profile_is_multidimensional(
    panel: Panel,
    *,
    year: int | None = None,
    threshold: float = 0.25,
) -> CompositeVerdict:
    """Decide whether a summed greenwashing score is defensible on this panel.

    `threshold` is the mean absolute phi below which the flags are treated as
    effectively independent. 0.25 is a judgement call, chosen so that the
    published correlations (which sit well below it) return "not defensible".
    """
    corr = correlation_matrix(panel, year=year)
    if not corr:
        return CompositeVerdict(float("nan"), float("nan"), 0, 0, False)
    values = list(corr.values())
    mean_abs = math.fsum(abs(v) for v in values) / len(values)
    return CompositeVerdict(
        mean_abs_phi=mean_abs,
        max_abs_phi=max(abs(v) for v in values),
        n_negative_pairs=sum(1 for v in values if v < 0),
        n_pairs=len(values),
        composite_defensible=mean_abs >= threshold,
    )


def from_assessments(assessments, *, year: int, sector: str | None = None) -> Panel:
    """Build a Panel from `arp.decarb.flags.assess` output, for analysis here.

    Companies with no climate claim are dropped. The framework measures the
    gap between a claim and the behaviour behind it, so a company that made no
    claim is not a clean one, it is out of scope. Including it would inflate
    the denominator and understate every prevalence relative to the published
    figures, which are reported among pledging companies.
    """
    from arp.decarb.schemas import FirmYear

    rows = [
        FirmYear(
            firm_id=a.firm_id,
            year=year,
            sector=sector,
            red_flags=dict(a.flags),
            metrics={k: v for k, v in (("peta", a.peta), ("ambition", a.ambition)) if v is not None},
        )
        for a in assessments
        if a.made_climate_claim
    ]
    return Panel(rows)
