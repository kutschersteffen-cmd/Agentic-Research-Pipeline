from __future__ import annotations

from collections import defaultdict
from math import fsum

from arp.index.fields import metric_value, resolve_missing
from arp.schemas.index import (
    AbsoluteThreshold,
    BestInClassCoverage,
    IndexCandidate,
    SelectAll,
    SelectionRule,
    StageTrace,
    TopN,
)


def _label(rule) -> str:
    return rule.label or rule.type


def _scored(
    candidates: list[IndexCandidate], field: str, missing, rule_label: str
) -> list[tuple[IndexCandidate, float]]:
    """Attaches the score, applying the missing-value policy. Companies
    dropped by a `fail` policy never reach the ranking at all, which is
    the right semantics: an unscored company cannot be ranked."""
    out = []
    for candidate in candidates:
        value = metric_value(candidate, field)
        if value is None:
            if resolve_missing(missing, rule_label=rule_label, field=field, company_id=candidate.company_id):
                value = 0.0
            else:
                continue
        out.append((candidate, value))
    return out


def _rank_key(higher_is_better: bool):
    """Deterministic total order: score, then float market cap, then
    company_id. Without the last two, tied scores would make selection
    depend on input ordering."""
    sign = -1.0 if higher_is_better else 1.0
    return lambda pair: (sign * pair[1], -pair[0].float_mcap, pair[0].company_id)


def _by_group(pairs: list[tuple[IndexCandidate, float]], dimension: str) -> dict[str, list[tuple[IndexCandidate, float]]]:
    groups: dict[str, list[tuple[IndexCandidate, float]]] = defaultdict(list)
    for candidate, score in pairs:
        groups[candidate.group_value(dimension)].append((candidate, score))
    return dict(groups)


def _select_coverage(rule: BestInClassCoverage, candidates: list[IndexCandidate], incumbents: set[str]) -> tuple[list[IndexCandidate], dict]:
    pairs = _scored(candidates, rule.score_field, rule.missing, _label(rule))
    selected: list[IndexCandidate] = []
    detail: dict[str, float | str | int] = {"groups": 0, "buffer_retained": 0}
    for group, members in sorted(_by_group(pairs, rule.group_by).items()):
        detail["groups"] = int(detail["groups"]) + 1
        members.sort(key=_rank_key(rule.higher_is_better))
        by_count = rule.basis == "count"
        total = float(len(members)) if by_count else fsum(c.float_mcap for c, _ in members)
        if total <= 0:
            continue
        target = rule.target_pct * total
        covered = 0.0
        for candidate, _score in members:
            size = 1.0 if by_count else candidate.float_mcap
            if covered >= target:
                # Buffer: an incumbent just past the target stays in, which
                # is what stops the index churning when a name drifts a
                # rank or two across a review. A non-incumbent does not get
                # in on the buffer -- the band is one-sided by design.
                if rule.buffer_pct > 0 and candidate.company_id in incumbents and covered < target * (1.0 + rule.buffer_pct):
                    selected.append(candidate)
                    covered += size
                    detail["buffer_retained"] = int(detail["buffer_retained"]) + 1
                    continue
                break
            selected.append(candidate)
            covered += size
        detail[f"coverage_{group}"] = round(covered / total, 6) if total else 0.0
    return selected, detail


def _select_absolute(rule: AbsoluteThreshold, candidates: list[IndexCandidate]) -> tuple[list[IndexCandidate], dict, list[str]]:
    pairs = _scored(candidates, rule.score_field, rule.missing, _label(rule))
    selected: list[IndexCandidate] = []
    exceptions: list[str] = []
    detail: dict[str, float | str | int] = {"empty_groups": 0}
    for group, members in sorted(_by_group(pairs, rule.group_by).items()):
        threshold = rule.group_thresholds.get(group, rule.threshold)
        if rule.higher_is_better:
            passing = [(c, s) for c, s in members if s >= threshold]
        else:
            passing = [(c, s) for c, s in members if s <= threshold]
        if not passing:
            # An absolute bar can empty a whole group where a relative rank
            # never can (ISS Prime is the published example). The fallback
            # is a methodology decision, so it is declared in the rule
            # rather than discovered in production.
            detail["empty_groups"] = int(detail["empty_groups"]) + 1
            if rule.on_empty_group == "block":
                raise ValueError(f"{_label(rule)}: no company in group {group!r} clears the threshold {threshold}")
            if rule.on_empty_group == "fallback_relative" and members:
                members.sort(key=_rank_key(rule.higher_is_better))
                take = max(1, round(rule.fallback_target_pct * len(members)))
                passing = members[:take]
                exceptions.append(
                    f"{_label(rule)}: group {group!r} had no company above the absolute threshold; "
                    f"fell back to the top {rule.fallback_target_pct:.0%} by rank ({take} names)"
                )
            else:
                exceptions.append(f"{_label(rule)}: group {group!r} left empty -- no company cleared the threshold")
        selected.extend(c for c, _ in passing)
    return selected, detail, exceptions


def _select_top_n(rule: TopN, candidates: list[IndexCandidate]) -> tuple[list[IndexCandidate], dict]:
    pairs = _scored(candidates, rule.score_field, rule.missing, _label(rule))
    selected: list[IndexCandidate] = []
    for _, members in sorted(_by_group(pairs, rule.group_by).items()):
        members.sort(key=_rank_key(rule.higher_is_better))
        selected.extend(c for c, _ in members[: rule.n])
    return selected, {"n": rule.n}


def apply_selection(
    candidates: list[IndexCandidate], rule: SelectionRule, incumbents: set[str] | None = None
) -> tuple[list[IndexCandidate], StageTrace, list[str]]:
    incumbents = incumbents or set()
    exceptions: list[str] = []
    if isinstance(rule, SelectAll) or not rule.enabled:
        selected, detail = list(candidates), {"note": "no selection step"}
    elif isinstance(rule, BestInClassCoverage):
        selected, detail = _select_coverage(rule, candidates, incumbents)
    elif isinstance(rule, AbsoluteThreshold):
        selected, detail, exceptions = _select_absolute(rule, candidates)
    elif isinstance(rule, TopN):
        selected, detail = _select_top_n(rule, candidates)
    else:  # pragma: no cover -- the discriminated union makes this unreachable
        raise ValueError(f"Unknown selection rule: {rule.type}")

    selected.sort(key=lambda c: c.company_id)
    kept = {c.company_id for c in selected}
    trace = StageTrace(
        stage="selection",
        rule_type=rule.type,
        label=_label(rule),
        candidates_in=len(candidates),
        candidates_out=len(selected),
        dropped_sample=[c.company_id for c in candidates if c.company_id not in kept][:10],
        detail=detail,
    )
    return selected, trace, exceptions
