"""Layer 4 entity and period consistency against the cited documents (E42)."""

from __future__ import annotations

from arp.schemas.datapoints import CheckOutcome, CheckResult, ExtractedField, FieldDefinition, Severity


def _result(check_id: str, outcome: CheckOutcome, severity: Severity = Severity.INFO, detail: str = "") -> list[CheckResult]:
    return [CheckResult(check_id=check_id, layer=4, outcome=outcome, severity=severity, detail=detail)]


def _cited_docs(field: ExtractedField, ctx) -> list:
    ids = dict.fromkeys(c.doc_id for c in field.citations if c.grounded)
    return [ctx.documents_by_id[i] for i in ids if i in ctx.documents_by_id]


def check_entity(spec: FieldDefinition, field: ExtractedField, ctx) -> list[CheckResult]:
    cid = "consistency.entity"
    docs = [d for d in _cited_docs(field, ctx) if d.match_status is not None]
    if not docs:
        return _result(cid, CheckOutcome.NOT_APPLICABLE)
    bad = next((d for d in docs if d.match_status == "mismatch"), None)
    if bad:
        return _result(cid, CheckOutcome.FAIL, Severity.BLOCK, f"{bad.doc_id} covers {bad.covered_entity}, not the issuer")
    amb = next((d for d in docs if d.match_status == "ambiguous"), None)
    if amb:
        return _result(cid, CheckOutcome.FAIL, Severity.WARN, f"{amb.doc_id} entity match is ambiguous")
    return _result(cid, CheckOutcome.PASS)


def check_period(spec: FieldDefinition, field: ExtractedField, ctx) -> list[CheckResult]:
    cid = "consistency.period"
    docs = [d for d in _cited_docs(field, ctx) if d.period_plan and d.period_plan.planned]
    if not field.period_end or not docs:
        return _result(cid, CheckOutcome.NOT_APPLICABLE)
    if any(field.period_end in d.period_plan.planned for d in docs):
        return _result(cid, CheckOutcome.PASS)
    # warn, not block: the plan is a year-token heuristic and can miss a period the document reports
    return _result(cid, CheckOutcome.FAIL, Severity.WARN, f"period {field.period_end} not reported by {docs[0].doc_id}")
