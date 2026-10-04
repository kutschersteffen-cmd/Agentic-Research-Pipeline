"""Layer 3 round-trip check (E49): undo the stored conversion and compare with the number as printed."""

from __future__ import annotations

import math

from arp.normalise.locale import citation_decimal, parse_number
from arp.normalise.units import lookup_unit, split_unit
from arp.normalise.value import PRINTED, unit_from_raw
from arp.schemas.datapoints import CheckOutcome, CheckResult, ExtractedField, FieldDefinition, Severity


def _result(outcome: CheckOutcome, detail: str = "") -> list[CheckResult]:
    return [CheckResult(check_id="round_trip", layer=3, outcome=outcome, severity=Severity.BLOCK, detail=detail)]


def check_round_trip(spec: FieldDefinition, field: ExtractedField, ctx) -> list[CheckResult]:
    na = CheckOutcome.NOT_APPLICABLE
    m = PRINTED.search(field.raw_value_text or "")
    if field.canonical_value is None or not m:
        return _result(na)
    printed = parse_number(m[0], citation_decimal(field.citations, ctx.documents_by_id))[0]
    if printed is None:
        return _result(na)

    # Forward: printed * scale * src.factor [* fx] / (dst scale * dst.factor). Undo it with the stored fields.
    src_text = field.unit or unit_from_raw(field.raw_value_text)
    src = lookup_unit(split_unit(src_text)[2]) if src_text else None
    dst_scale, _, dst_base = split_unit(field.canonical_unit or "")
    dst = lookup_unit(dst_base) if field.canonical_unit else None
    if (src is None) != (dst is None):
        return _result(na, "unit not readable; cannot reverse the conversion")
    back = field.canonical_value / (field.fx_rate or 1.0) / (field.scale_applied or 1.0)
    if src and dst:
        back *= dst_scale * dst.factor / src.factor

    # Sign and magnitude are compared apart: "(1,234)" prints without its sign in the matched digits.
    if math.isclose(abs(back), abs(printed), rel_tol=1e-6):
        return _result(CheckOutcome.PASS)
    return _result(CheckOutcome.FAIL, f"canonical value reverses to {back:g}, printed number is {printed:g}")
