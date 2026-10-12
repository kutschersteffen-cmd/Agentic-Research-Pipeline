"""Reviewer decisions on a run, turned into labelled cases for `golden-set precision`."""

from __future__ import annotations

from arp.golden_set.schema import ExpectedValue, RecordGoldenCase
from arp.orchestration.review_queue import FINAL_STATES, item_state
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import ValueState
from arp.schemas.review import DecisionKind, DecisionReason, ReviewDecision, field_item_key, period_key
from arp.storage.run_store import RunStore


def _state(value) -> ValueState:
    if value is None:
        return ValueState.NOT_FOUND
    return ValueState.ZERO if isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0 else ValueState.FOUND


def _expected(d: dict, field: dict) -> ExpectedValue | None:
    period = field.get("period_end")
    if d["decision"] == DecisionKind.APPROVE:
        value = field.get("value")
        state = ValueState(field["value_state"]) if "value_state" in field else _state(value)
    elif d["decision"] == DecisionKind.CORRECT and d["corrected_value"] is not None:
        value = d["corrected_value"]["value"]  # decide.py requires this key; None means "not disclosed"
        state, period = _state(value), d["corrected_value"].get("period_end") or period
    elif d["decision"] == DecisionKind.REJECT and d["reason_code"] == DecisionReason.NOT_DISCLOSED:
        value, state = None, ValueState.NOT_FOUND
    else:
        return None  # escalate, or a reject that says nothing about the right answer
    return ExpectedValue(field_id=field["field_id"], period_end=period, value=value, value_state=state)


def export_cases(run_store: RunStore, run_id: str, decisions: list[ReviewDecision]) -> list[RecordGoldenCase]:
    """One case per company with a usable decision. Only final decisions count: a first review still
    waiting for its second (or a disagreement, or an escalation) is not a label yet."""
    rows: dict[str, list[dict]] = {}
    for d in decisions:  # append order; ReviewDecision rows always carry a step, so no legacy co-sign rule applies
        rows.setdefault(d.item_key, []).append(d.model_dump(mode="json"))
    states = {k: item_state(v, cosigned_at=set(), cosign_required=set()) for k, v in rows.items()}
    last = {k: st.effective for k, st in states.items() if st.state in FINAL_STATES}
    refs = {c.company_id: c for c in run_store.load_companies(run_id) or []}
    cases = []
    for row in run_store.read_results(run_id):
        issuer = row.get("issuer_key", "")
        expected = []
        for f in row.get("fields", []):  # item keys are matched, not split: issuer keys contain ":"
            d = last.get(field_item_key(issuer, f["field_id"], period_key(f)))
            if d and (e := _expected(d, f)):
                expected.append(e)
        if expected:
            company = refs.get(row["company_id"]) or CompanyRef(
                company_id=row["company_id"], name=row.get("name") or row["company_id"], ticker=row.get("ticker")
            )
            cases.append(RecordGoldenCase(case_id=f"{run_id}:{company.company_id}", company=company, expected=expected))
    return cases
