from __future__ import annotations

from arp.index.fields import category_value, flag_value, metric_value, resolve_missing
from arp.schemas.index import (
    CategoryScreen,
    FlagExclusionScreen,
    IndexCandidate,
    MetricThresholdScreen,
    ScreenRule,
    StageTrace,
)

EPS = 1e-12


def _label(rule) -> str:
    return rule.label or rule.type


def _keep_metric(rule: MetricThresholdScreen, candidate: IndexCandidate) -> bool:
    value = metric_value(candidate, rule.field)
    if value is None:
        return resolve_missing(rule.missing, rule_label=_label(rule), field=rule.field, company_id=candidate.company_id)
    below = rule.min_value is not None and value < rule.min_value - EPS
    above = rule.max_value is not None and value > rule.max_value + EPS
    return not (below or above)


def _keep_flag(rule: FlagExclusionScreen, candidate: IndexCandidate) -> bool:
    value = flag_value(candidate, rule.field)
    if value is None:
        return resolve_missing(rule.missing, rule_label=_label(rule), field=rule.field, company_id=candidate.company_id)
    return value != rule.exclude_when


def _keep_category(rule: CategoryScreen, candidate: IndexCandidate) -> bool:
    value = category_value(candidate, rule.field)
    if value is None:
        return resolve_missing(rule.missing, rule_label=_label(rule), field=rule.field, company_id=candidate.company_id)
    denied = bool(rule.deny) and value in rule.deny
    outside_allow_list = bool(rule.allow) and value not in rule.allow
    return not (denied or outside_allow_list)


_KEEP = {
    "metric_threshold": _keep_metric,
    "flag_exclusion": _keep_flag,
    "category_screen": _keep_category,
}


def apply_screens(candidates: list[IndexCandidate], screens: list[ScreenRule]) -> tuple[list[IndexCandidate], list[StageTrace]]:
    """Applies screens in the order given, recording one trace line each.

    Order is part of the methodology and is preserved exactly: screens do
    not commute when a later one is rank- or coverage-based, and even when
    they do, the funnel numbers a committee reviews depend on the order
    they were applied in.
    """
    surviving = sorted(candidates, key=lambda c: c.company_id)
    traces: list[StageTrace] = []
    for rule in screens:
        if not rule.enabled:
            traces.append(
                StageTrace(
                    stage="screen",
                    rule_type=rule.type,
                    label=_label(rule),
                    candidates_in=len(surviving),
                    candidates_out=len(surviving),
                    detail={"skipped": "rule disabled"},
                )
            )
            continue
        keep_fn = _KEEP[rule.type]
        kept, dropped = [], []
        for candidate in surviving:
            (kept if keep_fn(rule, candidate) else dropped).append(candidate)
        traces.append(
            StageTrace(
                stage="screen",
                rule_type=rule.type,
                label=_label(rule),
                candidates_in=len(surviving),
                candidates_out=len(kept),
                dropped_sample=[c.company_id for c in dropped[:10]],
                detail={"field": rule.field, "dropped": len(dropped)},
            )
        )
        surviving = kept
    return surviving, traces
