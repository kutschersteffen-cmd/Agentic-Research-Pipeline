from __future__ import annotations

import math

from arp.schemas.decision import MechanismConfig, WeightPreset

_EPSILON = 1e-9


def breadth_adjusted_weight(criteria_count: int) -> float:
    """A dimension's default weight: the square root of how many criteria
    it holds. A theme measured seven ways should count for more than one
    measured once -- but not seven times more, which is what an unadjusted
    per-criterion weighting silently does."""
    return math.sqrt(max(1, criteria_count))


def entropy_weights(normalised_minmax: dict[str, list[float | None]]) -> dict[str, float]:
    """Shannon-entropy ("discriminating power") weights: a criterion that
    separates the field earns more weight than one on which everyone
    scores alike.

    Computed over each criterion's min-max normalised values treated as a
    distribution across entities, with a +1 offset so a zero value does
    not vanish from the log. Documented rather than implicit because it is
    the one weighting preset whose result cannot be read off the config.
    """
    weights: dict[str, float] = {}
    for column, values in normalised_minmax.items():
        present = [v + 1.0 for v in values if v is not None]
        total = sum(present)
        if len(present) < 2 or total <= 0:
            weights[column] = _EPSILON
            continue
        entropy = -sum((v / total) * math.log(v / total) for v in present if v > 0)
        divergence = 1.0 - entropy / math.log(len(present))
        weights[column] = max(divergence, _EPSILON)
    grand_total = sum(weights.values()) or 1.0
    return {c: w / grand_total for c, w in weights.items()}


def effective_weights(
    config: MechanismConfig,
    active_columns: list[str],
    normalised_minmax: dict[str, list[float | None]] | None = None,
    preset: WeightPreset | None = None,
) -> dict[str, float]:
    """Per-criterion weights summing to 1, under whichever preset applies.

    Weights are relative everywhere in the UI and normalised to 1 here, so
    a user can set a dimension to "2" without having to rebalance every
    other number by hand.
    """
    mode = preset or config.weighting
    if not active_columns:
        return {}
    if mode == "equal":
        return {c: 1.0 / len(active_columns) for c in active_columns}
    if mode == "entropy":
        if not normalised_minmax:
            return {c: 1.0 / len(active_columns) for c in active_columns}
        subset = {c: v for c, v in normalised_minmax.items() if c in active_columns}
        return entropy_weights(subset)

    by_column = {c.column: c for c in config.criteria}
    dimension_totals: dict[str, float] = {d.id: 0.0 for d in config.dimensions}
    for column in active_columns:
        criterion = by_column.get(column)
        if criterion and criterion.dimension_id in dimension_totals:
            dimension_totals[criterion.dimension_id] += max(0.0, criterion.weight)

    live_dimension_weight = sum(max(0.0, d.weight) for d in config.dimensions if dimension_totals.get(d.id, 0.0) > 0)
    if live_dimension_weight <= 0:
        return {c: 1.0 / len(active_columns) for c in active_columns}

    dimensions = {d.id: d for d in config.dimensions}
    weights: dict[str, float] = {}
    for column in active_columns:
        criterion = by_column.get(column)
        dimension = dimensions.get(criterion.dimension_id) if criterion else None
        total = dimension_totals.get(criterion.dimension_id, 0.0) if criterion else 0.0
        if not criterion or not dimension or total <= 0:
            weights[column] = 0.0
            continue
        weights[column] = (max(0.0, dimension.weight) / live_dimension_weight) * (max(0.0, criterion.weight) / total)
    return weights
