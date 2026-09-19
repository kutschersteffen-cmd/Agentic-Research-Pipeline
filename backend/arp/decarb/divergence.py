"""Divergence between transition-risk metrics.

Fliegel (2026) assembles eight firm-level transition risk metrics and shows
that between-group rank correlations are close to zero, while within-group
correlations run 0.58 to 0.73. All taxonomy-based proxies correlate
*negatively* with inverted emission-intensity metrics.

The consequence for applied work is design rule 5: a finding that holds under
one proxy is a description of that proxy. This module makes the check cheap,
so there is no excuse for not running it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from arp.decarb.schemas import Panel
from arp.decarb.stats import spearman

__all__ = ["DivergenceReport", "rank_correlation_matrix", "divergence_report", "rank_disagreement"]

# Grouping from Fliegel (2026), used to separate within- from between-group
# correlation. Callers with different metrics should pass their own mapping.
DEFAULT_GROUPS: dict[str, str] = {
    "taxonomy_capex": "taxonomy",
    "taxonomy_revenue": "taxonomy",
    "emission_intensity": "emissions",
    "emission_intensity_scope3": "emissions",
    "e_score_refinitiv": "score",
    "e_score_msci": "score",
    "trbc_class": "classification",
    "text_based": "text",
}


@dataclass(slots=True)
class DivergenceReport:
    within_group_mean: float
    between_group_mean: float
    n_metrics: int
    n_firms: int
    matrix: dict[tuple[str, str], float]

    @property
    def separation(self) -> float:
        """Within minus between. Fliegel's finding is that this is positive
        but small: metrics agree somewhat inside a family and barely at all
        across families."""
        return self.within_group_mean - self.between_group_mean

    def explain(self) -> str:
        return (
            f"{self.n_metrics} metrics over {self.n_firms} firms. "
            f"Mean within-group rank correlation {self.within_group_mean:.2f}, "
            f"between-group {self.between_group_mean:.2f} (separation {self.separation:+.2f}). "
            "Any result resting on a single metric should be re-run across families."
        )


def _metric_vectors(panel: Panel, *, year: int) -> dict[str, dict[str, float]]:
    """{metric_name: {firm_id: value}} for one year."""
    out: dict[str, dict[str, float]] = {}
    for row in panel.rows:
        if row.year != year:
            continue
        for name, value in row.metrics.items():
            out.setdefault(name, {})[row.firm_id] = value
    return out


def rank_correlation_matrix(panel: Panel, *, year: int) -> dict[tuple[str, str], float]:
    """Pairwise Spearman correlations across metrics, on common firms only."""
    vectors = _metric_vectors(panel, year=year)
    names = sorted(vectors)
    out: dict[tuple[str, str], float] = {}
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            common = sorted(set(vectors[a]) & set(vectors[b]))
            if len(common) < 3:
                continue
            out[(a, b)] = spearman([vectors[a][f] for f in common], [vectors[b][f] for f in common])
    return out


def divergence_report(
    panel: Panel,
    *,
    year: int,
    groups: dict[str, str] | None = None,
) -> DivergenceReport:
    """Within- against between-group mean rank correlation."""
    groups = groups or DEFAULT_GROUPS
    matrix = rank_correlation_matrix(panel, year=year)
    within = [v for (a, b), v in matrix.items() if groups.get(a) and groups.get(a) == groups.get(b)]
    between = [v for (a, b), v in matrix.items() if groups.get(a) and groups.get(b) and groups.get(a) != groups.get(b)]
    vectors = _metric_vectors(panel, year=year)
    firms = {f for v in vectors.values() for f in v}
    return DivergenceReport(
        within_group_mean=math.fsum(within) / len(within) if within else float("nan"),
        between_group_mean=math.fsum(between) / len(between) if between else float("nan"),
        n_metrics=len(vectors),
        n_firms=len(firms),
        matrix=matrix,
    )


def rank_disagreement(panel: Panel, *, year: int, metric_a: str, metric_b: str, top_n: int = 20) -> dict[str, int]:
    """Firms whose rank differs most between two metrics.

    Useful for sanity-checking a metric choice on named companies before
    committing to it for a whole study.
    """
    vectors = _metric_vectors(panel, year=year)
    if metric_a not in vectors or metric_b not in vectors:
        raise ValueError(f"metric not present in panel for {year}")
    common = sorted(set(vectors[metric_a]) & set(vectors[metric_b]))
    if not common:
        return {}
    ra = {f: i for i, f in enumerate(sorted(common, key=lambda f: vectors[metric_a][f]))}
    rb = {f: i for i, f in enumerate(sorted(common, key=lambda f: vectors[metric_b][f]))}
    gaps = {f: ra[f] - rb[f] for f in common}
    return dict(sorted(gaps.items(), key=lambda kv: -abs(kv[1]))[:top_n])
