"""Reviewer decisions on a run, turned into labelled cases for `golden-set precision`."""

from __future__ import annotations

from arp.checks.numeric import NUMERIC_TYPES, parse_number
from arp.golden_set.schema import ExpectedValue, RecordGoldenCase
from arp.orchestration.review_queue import FINAL_STATES, item_state
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import DataPointSchema, FieldDataType, ValueState
from arp.schemas.review import DecisionKind, DecisionReason, ReviewDecision, field_item_key, period_key
from arp.storage.run_store import RunStore


def _state(value) -> ValueState:
    if value is None:
        return ValueState.NOT_FOUND
    return ValueState.ZERO if isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0 else ValueState.FOUND


_BOOLEANS = {"true": True, "yes": True, "false": False, "no": False}


def _typed(value, data_type: FieldDataType | None):
    """A corrected value as the review UI sends it (text) in the field's type; text that does not parse stays text."""
    if not isinstance(value, str):
        return value
    value = value.strip()
    if not value:
        return None
    if data_type == FieldDataType.BOOLEAN:
        return _BOOLEANS.get(value.lower(), value)
    if data_type in NUMERIC_TYPES:
        number = parse_number(value)  # the parser review/decide.py checks corrected numbers with
        return value if number is None else number
    return value


def _expected(d: dict, field: dict, data_type: FieldDataType | None = None) -> ExpectedValue | None:
    period = field.get("period_end")
    if d["decision"] == DecisionKind.APPROVE:
        # The scaled value, so a later scale error (raw 1234 read as thousands, not millions) cannot match it.
        value = field["canonical_value"] if field.get("canonical_value") is not None else field.get("value")
        state = ValueState(field["value_state"]) if "value_state" in field else _state(value)
    elif d["decision"] == DecisionKind.CORRECT and d["corrected_value"] is not None:
        # decide.py requires this key; None means "not disclosed"
        value = _typed(d["corrected_value"]["value"], data_type)
        state, period = _state(value), d["corrected_value"].get("period_end") or period
    elif d["decision"] == DecisionKind.REJECT and d["reason_code"] == DecisionReason.NOT_DISCLOSED:
        value, state = None, ValueState.NOT_FOUND
    else:
        return None  # escalate, or a reject that says nothing about the right answer
    return ExpectedValue(field_id=field["field_id"], period_end=period, value=value, value_state=state)


def final_decisions(decisions: list[ReviewDecision]) -> dict[str, dict]:
    """Each item's effective decision, for items whose review is final (co-signed where required)."""
    rows: dict[str, list[dict]] = {}
    for d in decisions:  # append order; ReviewDecision rows always carry a step, so no legacy co-sign rule applies
        rows.setdefault(d.item_key, []).append(d.model_dump(mode="json"))
    states = {k: item_state(v, cosigned_at=set(), cosign_required=set()) for k, v in rows.items()}
    return {k: st.effective for k, st in states.items() if st.state in FINAL_STATES}


def export_cases(
    run_store: RunStore, run_id: str, decisions: list[ReviewDecision], *, schema: DataPointSchema | None = None,
) -> list[RecordGoldenCase]:
    """One case per company with a usable decision. Only final decisions count: a first review still
    waiting for its second (or a disagreement, or an escalation) is not a label yet. `schema` (the run's)
    types corrected values; without it they stay as the reviewer sent them."""
    data_types = {f.field_id: f.data_type for f in schema.fields} if schema else {}
    last = final_decisions(decisions)
    refs = {c.company_id: c for c in run_store.load_companies(run_id) or []}
    cases = []
    for row in run_store.read_results(run_id):
        issuer = row.get("issuer_key", "")
        expected = []
        for f in row.get("fields", []):  # item keys are matched, not split: issuer keys contain ":"
            d = last.get(field_item_key(issuer, f["field_id"], period_key(f)))
            if d and (e := _expected(d, f, data_types.get(f["field_id"]))):
                expected.append(e)
        if expected:
            company = refs.get(row["company_id"]) or CompanyRef(
                company_id=row["company_id"], name=row.get("name") or row["company_id"], ticker=row.get("ticker")
            )
            cases.append(RecordGoldenCase(case_id=f"{run_id}:{company.company_id}", company=company, expected=expected))
    return cases
