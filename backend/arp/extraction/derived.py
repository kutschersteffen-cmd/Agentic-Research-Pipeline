"""Derived criterion fields: a company-level yes/no from boolean fields by three-valued rule, no model call."""

from __future__ import annotations

from arp.schemas.datapoints import ExtractedField, FieldDefinition, ValueState, is_failing
from arp.schemas.review import ReasonCode


def _state(row: ExtractedField | None) -> bool | None:
    """True/False only for a found boolean; not_found, not_applicable, zero and a missing row are undecided."""
    if row is not None and row.value_state == ValueState.FOUND and isinstance(row.value, bool):
        return row.value
    return None


def evaluate_derived(spec: FieldDefinition, by_id: dict[str, ExtractedField]) -> ExtractedField:
    rule = spec.derived_rule
    assert rule is not None
    inputs = list(dict.fromkeys([*rule.all_of, *rule.any_of]))
    states = {i: _state(by_id.get(i)) for i in inputs}
    n_true = sum(s is True for s in states.values())
    n_undecided = sum(s is None for s in states.values())

    # Per part: satisfied, violated, or (neither) undecided. Not-disclosed never counts as False.
    parts: list[tuple[bool, bool]] = []
    if rule.all_of:
        s = [states[i] for i in rule.all_of]
        parts.append((all(x is True for x in s), any(x is False for x in s)))
    if rule.any_of:
        s = [states[i] for i in rule.any_of]
        parts.append((any(x is True for x in s), all(x is False for x in s)))
    if rule.min_true is not None:
        parts.append((n_true >= rule.min_true, n_true + n_undecided < rule.min_true))

    value: bool | None = None
    if any(violated for _, violated in parts):
        value = False
    elif all(satisfied for satisfied, _ in parts):
        value = True

    rows = [by_id[i] for i in inputs if i in by_id]
    cited = {True: [by_id[i] for i in inputs if states[i] is True], False: rows}.get(value, [])
    seen: dict[str, object] = {}
    for r in cited:
        for c in r.citations:
            seen.setdefault(c.model_dump_json(), c)

    flagged = any(r.review_reasons or any(is_failing(c) for c in r.checks) for r in rows)
    found = value is not None
    return ExtractedField(
        field_id=spec.field_id,
        field_name=spec.name,
        value=value,
        value_state=ValueState.FOUND if found else ValueState.NOT_FOUND,
        citations=list(seen.values()),
        confidence=1.0 if found else 0.0,
        grounded=found,
        review_reasons=[ReasonCode.CHECK_FAILED] if flagged else [],
        method="extracted",
        verifier_notes=f"Derived from {', '.join(inputs)}.",
    )
