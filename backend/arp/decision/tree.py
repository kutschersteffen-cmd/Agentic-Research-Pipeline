from __future__ import annotations

from arp.decision.dataset import Dataset
from arp.decision.parsing import to_bool, to_number
from arp.decision.profiling import quantile
from arp.schemas.decision import ColumnProfile, CriterionContribution, CutMode, GateRule, MechanismConfig

_MIN_BAND_SHARE = 0.1


def gate_hit(rule: GateRule, dataset: Dataset, profiles: dict[str, ColumnProfile], row_index: int) -> bool:
    """Evaluated against the raw cell, never the normalised score -- a gate
    is a statement about the world ("this company is expanding coal"), not
    about where the entity landed on a scale."""
    profile = profiles.get(rule.column)
    if profile is None:
        return False
    raw = dataset.rows[row_index].get(rule.column, "")
    if profile.type == "boolean":
        value = to_bool(raw)
        if value is None:
            return False
        return value == 1 if rule.op == "is" else value == 0
    if profile.type in ("numeric", "ordinal"):
        value = to_number(raw, profile.decimal_comma)
        threshold = to_number(rule.value, False)
        if value is None or threshold is None:
            return False
        if rule.op == "lt":
            return value < threshold
        if rule.op == "gt":
            return value > threshold
        return value == threshold
    left = str(raw).strip().lower()
    right = str(rule.value).strip().lower()
    return left != right if rule.op == "isnot" else left == right


def quantile_positions(cut_count: int) -> list[float]:
    """Descending quantile positions for `cut_count` cut-points, spread
    evenly between the 20th and 80th percentile -- which for the default
    four tiers is the 80/50/20 split."""
    if cut_count <= 0:
        return []
    if cut_count == 1:
        return [0.5]
    step = 0.6 / (cut_count - 1)
    return [round(0.8 - i * step, 6) for i in range(cut_count)]


def derive_cuts(scores: list[float | None], config: MechanismConfig) -> tuple[list[float], CutMode]:
    """Cut-points over the *eligible* field -- callers pass scores with
    gated-out and insufficient entities already masked to None, so the
    bands are drawn over who is actually in the running.

    Returns the cuts and the mode that actually produced them: a `breaks`
    request with too few distinct scores falls back to quantiles, and the
    result says so rather than silently claiming natural breaks.
    """
    cut_count = max(1, len(config.tiers) - 1)
    present = sorted(s for s in scores if s is not None)

    if config.cut_mode == "absolute":
        pinned = config.pinned_cuts or []
        if len(pinned) == cut_count:
            return list(pinned), "absolute"
        fallback = _quantile_cuts(present, cut_count)
        return fallback, "quantile"

    if len(present) < cut_count + 1:
        return _quantile_cuts(present, cut_count), "quantile"

    if config.cut_mode == "breaks":
        breaks = _natural_breaks(present, cut_count)
        if breaks is not None:
            return breaks, "breaks"
        return _quantile_cuts(present, cut_count), "quantile"

    return _quantile_cuts(present, cut_count), "quantile"


def _quantile_cuts(present: list[float], cut_count: int) -> list[float]:
    if not present:
        return [round(75 - 25 * i, 1) for i in range(cut_count)]
    return [round(quantile(present, q), 1) for q in quantile_positions(cut_count)]


def _natural_breaks(present: list[float], cut_count: int) -> list[float] | None:
    """Cuts at the widest gaps in the sorted scores, subject to a minimum
    band width so a single outlier cannot claim a whole tier to itself."""
    min_band = max(1, int(len(present) * _MIN_BAND_SHARE))
    gaps = [(present[i] - present[i - 1], i) for i in range(min_band, len(present) - min_band)]
    if not gaps:
        return None
    gaps.sort(key=lambda g: -g[0])
    picks: list[int] = []
    for _, i in gaps:
        if all(abs(p - i) >= min_band for p in picks):
            picks.append(i)
        if len(picks) == cut_count:
            break
    if len(picks) < cut_count:
        return None
    picks.sort(reverse=True)
    return [round((present[i] + present[i - 1]) / 2, 1) for i in picks]


def tier_for_score(score: float, cuts: list[float]) -> int:
    for index, cut in enumerate(cuts):
        if score >= cut:
            return index + 1
    return len(cuts) + 1


def dimension_scores(contributions: list[CriterionContribution], config: MechanismConfig) -> dict[str, float | None]:
    """A dimension's own score, weighted within the dimension. This is what
    the veto reads: a strong overall score that hides one failed dimension
    is exactly the case a single average cannot show."""
    dimension_of = {c.column: c.dimension_id for c in config.criteria}
    accumulated: dict[str, list[float]] = {d.id: [0.0, 0.0] for d in config.dimensions}
    for contribution in contributions:
        if contribution.normalised is None:
            continue
        dimension_id = dimension_of.get(contribution.column)
        if dimension_id not in accumulated:
            continue
        accumulated[dimension_id][0] += contribution.normalised * contribution.weight
        accumulated[dimension_id][1] += contribution.weight
    return {d.id: (accumulated[d.id][0] / accumulated[d.id][1] if accumulated[d.id][1] > 0 else None) for d in config.dimensions}


def veto_dimensions(config: MechanismConfig, active_columns: list[str]) -> list[str]:
    """Only dimensions measured by at least `veto.min_criteria` criteria
    can demote. A dimension resting on one yes/no answer would otherwise
    let a single binary field override the whole framework."""
    if not config.veto.enabled:
        return []
    counts: dict[str, int] = {}
    by_column = {c.column: c for c in config.criteria}
    for column in active_columns:
        criterion = by_column.get(column)
        if criterion:
            counts[criterion.dimension_id] = counts.get(criterion.dimension_id, 0) + 1
    return [d.id for d in config.dimensions if counts.get(d.id, 0) >= config.veto.min_criteria]
