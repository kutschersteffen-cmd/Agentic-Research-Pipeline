"""Construction of the dependent variable.

Design rule 1 in the review: build the label before the features. A
decarbonisation label has to survive three things that routinely corrupt it.

1. Perimeter change. If a firm leaves the sample its emissions leave with
   it, and an aggregate that includes entries and exits measures the sample
   rather than the firms. `chained_change` holds the perimeter constant.
2. Scope 2 basis drift. Handled by `Panel` validation in schemas.py.
3. Single-year noise. Restatements, acquisitions and disposals produce
   large one-year swings that have nothing to do with abatement, which is
   why `decarboniser_labels` defaults to a multi-year window.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from arp.decarb.schemas import EmissionsBasis, FirmYear, Panel
from arp.decarb.stats import winsorise

__all__ = [
    "ChainedResult",
    "annualised_change",
    "chained_change",
    "decarboniser_labels",
    "forward_labels",
    "perimeter_effect",
]


@dataclass(slots=True)
class ChainedResult:
    """Aggregate change over a window, split into chained and perimeter parts.

    `chained_pct` is the change across firms present in both years.
    `aggregate_pct` is the change across everything in the sample.
    The difference between them is the compositional effect that LSEG (2026)
    find dominates portfolio-level carbon metrics.
    """

    start_year: int
    end_year: int
    aggregate_pct: float
    chained_pct: float
    n_continuing: int
    n_entered: int
    n_exited: int

    @property
    def composition_pct(self) -> float:
        return self.aggregate_pct - self.chained_pct


def annualised_change(first: float, last: float, years: int) -> float:
    """Compound annual growth rate. Returns nan for non-positive inputs.

    Non-positive emissions are returned as nan rather than raising, because
    net-of-removals reporting legitimately produces them and the caller
    should decide whether to drop or to treat separately.
    """
    if years <= 0:
        raise ValueError("years must be positive")
    if first <= 0.0 or last <= 0.0:
        return float("nan")
    return (last / first) ** (1.0 / years) - 1.0


def chained_change(panel: Panel, start_year: int, end_year: int) -> ChainedResult:
    """Aggregate against constant-perimeter change in Scope 1+2.

    This is the firm-level analogue of LSEG's chained emissions series. The
    gap it exposes is the point of the exercise: in the high-yield bond
    universe their aggregate series fell 9% a year while the chained series
    fell 2%, meaning almost all of the headline decline was turnover.
    """
    start = panel.by_year(start_year)
    end = panel.by_year(end_year)
    if not start or not end:
        raise ValueError(f"panel has no rows for {start_year} and/or {end_year}")

    def total(rows) -> float:
        return math.fsum(r.scope12 for r in rows if r.scope12 is not None)

    continuing = sorted(set(start) & set(end))
    entered = sorted(set(end) - set(start))
    exited = sorted(set(start) - set(end))

    agg_start, agg_end = total(start.values()), total(end.values())
    ch_start = total(start[f] for f in continuing)
    ch_end = total(end[f] for f in continuing)

    return ChainedResult(
        start_year=start_year,
        end_year=end_year,
        aggregate_pct=(agg_end / agg_start - 1.0) if agg_start > 0 else float("nan"),
        chained_pct=(ch_end / ch_start - 1.0) if ch_start > 0 else float("nan"),
        n_continuing=len(continuing),
        n_entered=len(entered),
        n_exited=len(exited),
    )


def perimeter_effect(panel: Panel, years: list[int]) -> list[ChainedResult]:
    """Chained decomposition for each consecutive pair of years."""
    ordered = sorted(years)
    return [chained_change(panel, a, b) for a, b in zip(ordered, ordered[1:])]


def decarboniser_labels(
    panel: Panel,
    *,
    start_year: int,
    end_year: int,
    disclosed_only: bool = True,
    threshold: float = 0.0,
    winsor: tuple[float, float] | None = (0.01, 0.99),
) -> dict[str, tuple[float, bool]]:
    """Firm-level annualised Scope 1+2 change over a window, plus a binary label.

    Returns {firm_id: (annualised_rate, is_decarboniser)} for firms present
    in both years with usable emissions in each.

    `disclosed_only` defaults to True. Training on vendor-estimated
    emissions means learning the estimation model, and LSEG report that the
    wide dispersion in their lowest governance band "largely disappears
    among disclosed emitters", which is what that contamination looks like
    from the outside.

    `threshold` is the annualised rate below which a firm counts as
    decarbonising. Zero is the natural default; a stricter test might use
    a sector pathway rate.
    """
    if end_year <= start_year:
        raise ValueError("end_year must be after start_year")
    start = panel.by_year(start_year)
    end = panel.by_year(end_year)
    span = end_year - start_year

    pairs: list[tuple[str, float]] = []
    for firm_id in sorted(set(start) & set(end)):
        a, b = start[firm_id], end[firm_id]
        if disclosed_only and (a.basis is not EmissionsBasis.REPORTED or b.basis is not EmissionsBasis.REPORTED):
            continue
        if a.scope12 is None or b.scope12 is None:
            continue
        rate = annualised_change(a.scope12, b.scope12, span)
        if math.isnan(rate):
            continue
        pairs.append((firm_id, rate))

    if not pairs:
        return {}

    rates = [r for _, r in pairs]
    if winsor is not None:
        rates = winsorise(rates, lower=winsor[0], upper=winsor[1])
    return {fid: (rate, rate < threshold) for (fid, _), rate in zip(pairs, rates)}


def forward_labels(
    panel: Panel,
    *,
    horizon: int = 3,
    disclosed_only: bool = True,
    threshold: float = 0.0,
) -> dict[tuple[str, int], tuple[float, bool]]:
    """Forward-looking label keyed by (firm_id, base_year).

    The rate covers the window (base_year, base_year + horizon]. Features
    observed at or before base_year can therefore be used to predict it
    without the feature window overlapping the outcome window.

    This separation is not optional. A label computed over the whole sample
    period and paired with features drawn from inside that period leaks: the
    lagged emissions growth used as a persistence baseline is part of the
    series the label is computed from, and any model will look excellent for
    a reason that has nothing to do with prediction.
    """
    if horizon < 1:
        raise ValueError("horizon must be at least 1 year")
    out: dict[tuple[str, int], tuple[float, bool]] = {}
    for firm_id in panel.firm_ids:
        series = {r.year: r for r in panel.firm_series(firm_id)}
        for base_year, row in series.items():
            target = series.get(base_year + horizon)
            if target is None:
                continue
            if disclosed_only and (
                row.basis is not EmissionsBasis.REPORTED or target.basis is not EmissionsBasis.REPORTED
            ):
                continue
            if row.scope12 is None or target.scope12 is None:
                continue
            rate = annualised_change(row.scope12, target.scope12, horizon)
            if math.isnan(rate):
                continue
            out[(firm_id, base_year)] = (rate, rate < threshold)
    return out
