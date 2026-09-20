from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from arp.schemas.decision import CriterionContribution, MissingPolicy

NEUTRAL = 50.0
PENALTY = 25.0


@dataclass
class RowScore:
    score: float | None = None
    coverage: float = 0.0
    grounded_coverage: float | None = None
    contributions: list[CriterionContribution] = field(default_factory=list)


def compute_scores(
    normalised: dict[str, list[float | None]],
    weights: dict[str, float],
    *,
    missing: MissingPolicy,
    row_count: int,
    confidence: dict[str, list[float | None]] | None = None,
    confidence_min: float = 0.8,
) -> list[RowScore]:
    """The weighted score itself, plus the two coverage figures that decide
    whether it is allowed to stand.

    `coverage` is the share of total weight backed by a present value.
    `grounded_coverage` is the share backed by a value whose confidence
    clears `confidence_min` -- which is what separates a score resting on
    independently verified extractions from one resting on the model's
    unverified word for it. It is None when the source supplied no
    confidence at all, because 'unknown' and 'unverified' are not the
    same claim.
    """
    columns = [c for c in weights if weights[c] > 0]
    column_means = {
        c: (statistics.fmean([v for v in normalised[c] if v is not None]) if any(v is not None for v in normalised[c]) else NEUTRAL)
        for c in columns
    }
    has_confidence = bool(confidence) and any(c in (confidence or {}) for c in columns)

    results: list[RowScore] = []
    for i in range(row_count):
        numerator = 0.0
        weight_present = 0.0
        weight_grounded = 0.0
        weight_all = 0.0
        weight_used = 0.0
        contributions: list[CriterionContribution] = []

        for column in columns:
            w = weights[column]
            weight_all += w
            raw = normalised[column][i]
            conf = (confidence or {}).get(column, [None] * row_count)[i] if has_confidence else None
            low_confidence = raw is not None and conf is not None and conf < confidence_min

            if raw is None:
                if missing == "neutral":
                    value = NEUTRAL
                elif missing == "mean":
                    value = column_means[column]
                elif missing == "penalise":
                    value = PENALTY
                else:
                    # "renormalise": nothing is invented -- the criterion
                    # simply leaves this entity's weight base.
                    contributions.append(CriterionContribution(column=column, normalised=None, weight=w, contribution=0.0))
                    continue
                imputed = True
            else:
                value = raw
                imputed = False
                weight_present += w
                if conf is None or conf >= confidence_min:
                    weight_grounded += w

            numerator += value * w
            weight_used += w
            contributions.append(
                CriterionContribution(
                    column=column, normalised=value, weight=w, contribution=0.0, imputed=imputed, low_confidence=low_confidence
                )
            )

        score = numerator / weight_used if weight_used > 0 else None
        for contribution in contributions:
            if contribution.normalised is not None and weight_used > 0:
                contribution.contribution = (contribution.weight / weight_used) * (contribution.normalised - NEUTRAL)

        results.append(
            RowScore(
                score=score,
                coverage=(weight_present / weight_all) if weight_all > 0 else 0.0,
                grounded_coverage=((weight_grounded / weight_all) if weight_all > 0 else 0.0) if has_confidence else None,
                contributions=contributions,
            )
        )
    return results


def ranks_of(scores: list[float | None]) -> list[int | None]:
    """Dense competition ranking, best first. None scores are unranked --
    an entity that was gated out or never scored does not occupy a place
    in the ordering."""
    ordered = sorted((i for i, s in enumerate(scores) if s is not None), key=lambda i: -scores[i])
    out: list[int | None] = [None] * len(scores)
    for position, i in enumerate(ordered):
        out[i] = position + 1
    return out
