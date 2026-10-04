"""Layer 5 cross-source check (E39): the value against the same figure from another source."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from arp.checks.plausibility import numeric_of
from arp.checks.runner import threshold_ref
from arp.schemas.datapoints import CheckOutcome, CheckResult, ExtractedField, FieldDefinition, Severity
from arp.schemas.review import field_item_key, period_key


class Reference(BaseModel):
    source: Literal["tagged", "text", "published"]
    value: float
    unit: str | None = None


def _result(outcome: CheckOutcome, detail: str = "", ref: str | None = None) -> list[CheckResult]:
    return [CheckResult(check_id="cross_source", layer=5, outcome=outcome, severity=Severity.WARN, detail=detail, threshold_ref=ref)]


def check_cross_source(spec: FieldDefinition, field: ExtractedField, ctx) -> list[CheckResult]:
    value = numeric_of(field)
    refs = ctx.references.get(field_item_key(ctx.issuer_key, field.field_id, period_key(field)), [])
    refs = [r for r in refs if r.unit is None or field.canonical_unit is None or r.unit == field.canonical_unit]
    if value is None or not refs:
        return _result(CheckOutcome.NOT_APPLICABLE)
    tol = spec.check_config.cross_source_tolerance
    ref = threshold_ref(spec, "cross_source_tolerance")
    bad = [r for r in refs if abs(value - r.value) / max(abs(r.value), 1e-9) > tol]
    if bad:
        return _result(CheckOutcome.FAIL, "; ".join(f"{r.source} {r.value:g} vs extracted {value:g}" for r in bad), ref)
    return _result(CheckOutcome.PASS, ref=ref)
