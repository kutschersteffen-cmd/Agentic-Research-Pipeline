"""Three-way routing (E68): rules only, no model call. The route is the system's decision;
it lives on the result row and never in review_decisions.jsonl."""

from __future__ import annotations

from dataclasses import dataclass

from arp.schemas.datapoints import (
    ExtractedField,
    FieldDefinition,
    FieldQuality,
    FieldStatus,
    RouteKind,
    ValueState,
    is_failing,
)


@dataclass(frozen=True)
class Route:
    kind: RouteKind
    reasons: list[str]


def route(
    field: ExtractedField, quality: FieldQuality, spec: FieldDefinition, *, held: str | None = None, trial: bool = False
) -> Route:
    """`trial`: the run is a trial, so every non-held row goes to review, rule skips included."""
    if held:
        return Route(RouteKind.HOLD, [held])
    if "not_applicable_by_rule" in field.route_reasons:
        if trial:
            return Route(RouteKind.REVIEW, ["unreleased_version", "not_applicable_by_rule"])
        return Route(RouteKind.AUTO_ACCEPT, ["not_applicable_by_rule"])
    reasons: list[str] = []
    if trial or spec.status != FieldStatus.RELEASED:
        reasons.append("unreleased_version")
    reasons += [str(r) for r in field.review_reasons]
    if field.value_state in (ValueState.FOUND, ValueState.ZERO) and not field.grounded and "not_grounded" not in reasons:
        reasons.append("not_grounded")  # defence in depth: the grounding gate never relies on the reason alone
    reasons += [f"check:{r.check_id}" for r in field.checks if is_failing(r)]
    if not quality.first_audit_passed:
        reasons.append("first_audit_pending")
    if field.value_state in (ValueState.FOUND, ValueState.ZERO, ValueState.NOT_APPLICABLE) and field.confidence < spec.auto_accept_min:
        reasons.append("below_auto_accept_min")
    if field.value_state == ValueState.NOT_FOUND and spec.high_risk:
        reasons.append("high_risk_not_found")
    return Route(RouteKind.REVIEW, reasons) if reasons else Route(RouteKind.AUTO_ACCEPT, [])
