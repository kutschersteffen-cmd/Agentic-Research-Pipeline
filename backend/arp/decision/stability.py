from __future__ import annotations

from arp.decision.scoring import ranks_of
from arp.schemas.decision import NormMethod

# The alternative specifications every entity is re-scored under. A ranking
# that only survives one arbitrary weighting choice is not a ranking, it is
# an artefact of that choice -- so the rank *range* across these is
# reported alongside the rank itself.
ALTERNATIVE_PRESETS = ("equal", "entropy")


def alternative_norm(method: NormMethod) -> NormMethod:
    """The contrasting normalisation: rank-based vs. value-based. Swapping
    percentile for z-score is the specification change most likely to move
    a ranking, because it is the one that stops ignoring outliers."""
    return "minmax" if method == "zscore" else "zscore"


def rank_ranges(specification_scores: list[list[float | None]]) -> tuple[list[int | None], list[int | None]]:
    """Per entity, the best and worst rank it holds across every
    specification. Entities masked out of the eligible field stay
    unranked in all of them."""
    all_ranks = [ranks_of(scores) for scores in specification_scores]
    n = len(specification_scores[0]) if specification_scores else 0
    minima: list[int | None] = []
    maxima: list[int | None] = []
    for i in range(n):
        values = [ranks[i] for ranks in all_ranks if ranks[i] is not None]
        minima.append(min(values) if values else None)
        maxima.append(max(values) if values else None)
    return minima, maxima
