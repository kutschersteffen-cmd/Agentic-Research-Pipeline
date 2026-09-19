"""Indicator saturation and rarity weighting.

This module implements design rule 3 of the review, and it is the piece I
think is most often missing from applied work in this area.

The motivating result is Dietz & Hastreiter (2026). They measure climate
management with TPI Management Quality indicators three ways: a raw count of
satisfied indicators, a hierarchical level, and a score that weights less
commonly implemented and more demanding practices more heavily. After firms
adopt long-term net zero targets the count shows no effect, the level shows a
*negative* effect significant at t+3, and the weighted score shows positive,
increasing and significant effects. Their explanation is that non-adopters
caught up on the basic practices.

The general principle: an indicator's information content depends on how many
firms satisfy it, and that changes every year. An indicator satisfied by 5% of
firms separates them; the same indicator at 95% separates nobody. A feature
set frozen at its construction date decays silently.

So: measure prevalence and discriminatory power per indicator per period,
weight by rarity, and treat the decay as a result rather than a nuisance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from arp.decarb.schemas import Panel
from arp.decarb.stats import auc, auc_stratified

__all__ = [
    "IndicatorYear",
    "prevalence_by_year",
    "discriminatory_power",
    "rarity_weights",
    "weighted_score",
    "saturation_report",
]


@dataclass(slots=True)
class IndicatorYear:
    """Prevalence and discriminatory power of one indicator in one year."""

    indicator: str
    year: int
    prevalence: float
    n: int
    auc: float | None = None

    @property
    def rarity_weight(self) -> float:
        """Inverse-prevalence weight, ln(1/p), the information content of
        the indicator being satisfied. Zero when nobody satisfies it."""
        if self.prevalence <= 0.0:
            return 0.0
        return math.log(1.0 / self.prevalence)

    @property
    def is_saturated(self) -> bool:
        """Conventional threshold: above 90% an indicator is hygiene, not signal."""
        return self.prevalence >= 0.90


def prevalence_by_year(panel: Panel, indicator: str) -> dict[int, IndicatorYear]:
    """Share of firms satisfying an indicator, per year."""
    out: dict[int, IndicatorYear] = {}
    for year in panel.years:
        rows = [r for r in panel.rows if r.year == year and indicator in r.indicators]
        if not rows:
            continue
        hits = sum(1 for r in rows if r.indicators[indicator])
        out[year] = IndicatorYear(indicator, year, hits / len(rows), len(rows))
    return out


def discriminatory_power(
    panel: Panel,
    indicator: str,
    labels: dict[str, bool],
    *,
    year: int | None = None,
    stratify_by: str | None = "sector",
) -> float:
    """AUC of a binary indicator against the decarbonisation label.

    0.5 means the indicator carries no information about which firms went on
    to decarbonise. Measured against a *forward* label, so the panel year
    should precede the label window; `saturation_report` does not enforce
    that ordering because the caller owns the research design.

    `stratify_by` defaults to "sector" because sector is the dominant
    determinant of emissions trajectories. An unstratified AUC on a panel
    where one sector is growing fast will mostly rank sectors, and an
    indicator that happens to be more common there will score below 0.5 even
    when it is associated with lower emissions inside every sector. Pass None
    for the pooled figure, but do not interpret it as a measure of the
    indicator.
    """
    rows = [r for r in panel.rows if indicator in r.indicators and r.firm_id in labels]
    if year is not None:
        rows = [r for r in rows if r.year == year]
    if not rows:
        return 0.5
    scores = [1.0 if r.indicators[indicator] else 0.0 for r in rows]
    ys = [labels[r.firm_id] for r in rows]
    if stratify_by is None:
        return auc(scores, ys)
    strata = [getattr(r, stratify_by, None) for r in rows]
    return auc_stratified(scores, ys, strata)


def rarity_weights(panel: Panel, indicators: list[str], *, year: int) -> dict[str, float]:
    """Normalised inverse-prevalence weights for a set of indicators.

    This is the operational form of Dietz & Hastreiter's weighted MQ score.
    Weights sum to 1 so that scores are comparable across years even as the
    prevalence mix shifts.
    """
    raw: dict[str, float] = {}
    for ind in indicators:
        by_year = prevalence_by_year(panel, ind)
        if year in by_year:
            raw[ind] = by_year[year].rarity_weight
    total = math.fsum(raw.values())
    if total <= 0.0:
        n = len(raw) or 1
        return {k: 1.0 / n for k in raw}
    return {k: v / total for k, v in raw.items()}


def weighted_score(panel: Panel, indicators: list[str], *, year: int) -> dict[str, float]:
    """Rarity-weighted governance score per firm, alongside the raw count.

    Returns {firm_id: weighted_score}. Compare against a plain count to see
    the divergence Dietz & Hastreiter document: the two measures can move in
    opposite directions once the easy indicators saturate.
    """
    weights = rarity_weights(panel, indicators, year=year)
    out: dict[str, float] = {}
    for row in panel.rows:
        if row.year != year:
            continue
        out[row.firm_id] = math.fsum(w for ind, w in weights.items() if row.indicators.get(ind))
    return out


def raw_count(panel: Panel, indicators: list[str], *, year: int) -> dict[str, int]:
    """Unweighted count of satisfied indicators, the comparator."""
    return {
        r.firm_id: sum(1 for ind in indicators if r.indicators.get(ind))
        for r in panel.rows
        if r.year == year
    }


def saturation_report(
    panel: Panel,
    indicators: list[str],
    labels: dict[str, bool] | None = None,
    *,
    stratify_by: str | None = "sector",
) -> list[IndicatorYear]:
    """Prevalence and, where labels are supplied, AUC for every indicator-year.

    Sorted by indicator then year so the decay in a given indicator's
    discriminatory power reads down the table.
    """
    out: list[IndicatorYear] = []
    for ind in indicators:
        for year, entry in sorted(prevalence_by_year(panel, ind).items()):
            if labels:
                entry.auc = discriminatory_power(panel, ind, labels, year=year, stratify_by=stratify_by)
            out.append(entry)
    return out
