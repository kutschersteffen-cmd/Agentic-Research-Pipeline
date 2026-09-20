from __future__ import annotations

from collections import defaultdict
from math import fsum, sqrt

from arp.index.fields import EPS, category_value, metric_value, resolve_missing
from arp.schemas.index import (
    BaseWeighting,
    BucketTilt,
    IndexCandidate,
    MetricTilt,
    StageTrace,
    TiltRule,
)


def _label(rule) -> str:
    return rule.label or rule.type


def normalise(weights: dict[str, float]) -> dict[str, float]:
    """Scales to sum 1. Summation is over a fixed key order via `fsum`, so
    the result does not depend on dict insertion order -- one of the
    determinism requirements in the build plan."""
    total = fsum(weights[k] for k in sorted(weights))
    if total <= 0:
        raise ValueError("Cannot normalise weights summing to zero")
    return {k: v / total for k, v in weights.items()}


def base_weights(candidates: list[IndexCandidate], scheme: BaseWeighting) -> dict[str, float]:
    raw: dict[str, float] = {}
    for candidate in candidates:
        if scheme.scheme == "free_float_mcap":
            value = candidate.float_mcap
        elif scheme.scheme == "equal":
            value = 1.0
        else:
            metric = metric_value(candidate, scheme.field or "")
            if metric is None:
                raise ValueError(f"base weighting '{scheme.scheme}' needs field {scheme.field!r} on {candidate.company_id!r}")
            # inverse_metric's floor stops a near-zero value dominating the index.
            value = max(metric, 0.0) if scheme.scheme == "metric" else candidate.float_mcap / max(metric, scheme.floor)
        raw[candidate.company_id] = value
    if fsum(raw[k] for k in sorted(raw)) <= 0:
        raise ValueError(f"base weighting '{scheme.scheme}' produced no positive weight")
    return normalise(raw)


def _metric_multipliers(rule: MetricTilt, candidates: list[IndexCandidate]) -> dict[str, float]:
    values: dict[str, float] = {}
    for candidate in candidates:
        value = metric_value(candidate, rule.field)
        if value is None:
            if resolve_missing(rule.missing, rule_label=_label(rule), field=rule.field, company_id=candidate.company_id):
                value = 0.0
            else:
                value = 0.0  # a 'fail' policy at the tilt stage means no tilt credit, not exclusion
        values[candidate.company_id] = value

    groups: dict[str, list[str]] = defaultdict(list)
    for candidate in candidates:
        groups[candidate.group_value(rule.group_by if rule.normalisation == "group_max" else "none")].append(candidate.company_id)

    scaled: dict[str, float] = {}
    for _group, members in sorted(groups.items()):
        member_values = [values[m] for m in sorted(members)]
        if rule.normalisation == "none":
            for m in members:
                scaled[m] = values[m]
        elif rule.normalisation in ("max", "group_max"):
            peak = max((abs(v) for v in member_values), default=0.0)
            for m in members:
                scaled[m] = values[m] / peak if peak > EPS else 1.0
        elif rule.normalisation == "rank_percentile":
            order = sorted(sorted(members), key=lambda m: (values[m], m))
            n = len(order)
            for rank, m in enumerate(order):
                scaled[m] = (rank + 0.5) / n if n else 0.5
        else:  # zscore, squashed into 0..1 so the tilt stays bounded before floor/ceiling
            n = len(member_values)
            mean = fsum(member_values) / n if n else 0.0
            var = fsum((v - mean) ** 2 for v in member_values) / n if n else 0.0
            sd = sqrt(var)
            for m in members:
                z = (values[m] - mean) / sd if sd > EPS else 0.0
                scaled[m] = 0.5 + max(-3.0, min(3.0, z)) / 6.0

    multipliers: dict[str, float] = {}
    span = rule.ceiling - rule.floor
    for company_id, value in scaled.items():
        position = value if rule.higher_is_better else 1.0 - value
        position = max(0.0, min(1.0, position)) if rule.normalisation != "none" else position
        raw = rule.floor + span * position if rule.normalisation != "none" else position
        multipliers[company_id] = max(rule.floor, min(rule.ceiling, raw))
    return multipliers


def _bucket_multipliers(rule: BucketTilt, candidates: list[IndexCandidate]) -> dict[str, float]:
    multipliers: dict[str, float] = {}
    for candidate in candidates:
        value = category_value(candidate, rule.field)
        if value is None:
            if not resolve_missing(rule.missing, rule_label=_label(rule), field=rule.field, company_id=candidate.company_id):
                multipliers[candidate.company_id] = rule.default_multiplier
                continue
            value = ""
        multipliers[candidate.company_id] = rule.multipliers.get(value, rule.default_multiplier)
    return multipliers


def apply_tilts(
    weights: dict[str, float], candidates: list[IndexCandidate], tilts: list[TiltRule]
) -> tuple[dict[str, float], dict[str, float], list[StageTrace]]:
    """Applies tilts in order, multiplicatively, renormalising after each.

    Returns the tilted weights, the cumulative multiplier per company (for
    the constituent record, so a reviewer can see exactly how far a name
    moved from its base weight), and one trace line per rule.
    """
    current = dict(weights)
    cumulative = {c.company_id: 1.0 for c in candidates}
    traces: list[StageTrace] = []
    for rule in tilts:
        if not rule.enabled:
            traces.append(
                StageTrace(stage="tilt", rule_type=rule.type, label=_label(rule), candidates_in=len(current), candidates_out=len(current), detail={"skipped": "rule disabled"})
            )
            continue
        if isinstance(rule, MetricTilt):
            multipliers = _metric_multipliers(rule, candidates)
        elif isinstance(rule, BucketTilt):
            multipliers = _bucket_multipliers(rule, candidates)
        else:  # pragma: no cover -- unreachable through the discriminated union
            raise ValueError(f"Unknown tilt rule: {rule.type}")

        before = dict(current)
        current = normalise({k: v * multipliers.get(k, 1.0) for k, v in current.items()})
        for company_id, multiplier in multipliers.items():
            cumulative[company_id] = cumulative.get(company_id, 1.0) * multiplier
        moved = fsum(abs(current[k] - before[k]) for k in sorted(current)) / 2.0
        traces.append(
            StageTrace(
                stage="tilt",
                rule_type=rule.type,
                label=_label(rule),
                candidates_in=len(current),
                candidates_out=len(current),
                detail={
                    "field": rule.field,
                    "weight_moved_pct": round(moved * 100, 4),
                    "min_multiplier": round(min(multipliers.values(), default=1.0), 6),
                    "max_multiplier": round(max(multipliers.values(), default=1.0), 6),
                },
            )
        )
    return current, cumulative, traces


def weighted_average(weights: dict[str, float], values: dict[str, float]) -> float | None:
    """Index-weighted average over the names that actually have a value,
    renormalised onto that covered subset. Returns None when nothing is
    covered, so a missing metric never silently reads as zero."""
    keys = sorted(k for k in weights if k in values)
    covered = fsum(weights[k] for k in keys)
    if covered <= EPS:
        return None
    return fsum(weights[k] * values[k] for k in keys) / covered
