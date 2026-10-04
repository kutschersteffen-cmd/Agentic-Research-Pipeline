"""Layer 3 checks: range, sign, percentage, part-of-whole and sum identity (E36)."""

from __future__ import annotations

from arp.checks.runner import threshold_ref
from arp.schemas.datapoints import (
    CheckOutcome,
    CheckResult,
    ExtractedField,
    FieldDataType,
    FieldDefinition,
    Severity,
)

_NA = CheckOutcome.NOT_APPLICABLE


def numeric_of(f: ExtractedField) -> float | None:
    if f.canonical_value is not None:
        return f.canonical_value
    if isinstance(f.value, (int, float)) and not isinstance(f.value, bool):
        return float(f.value)
    return None


def _result(check_id: str, severity: Severity, outcome: CheckOutcome, detail: str = "", ref: str | None = None):
    return [CheckResult(check_id=check_id, layer=3, outcome=outcome, severity=severity, detail=detail, threshold_ref=ref)]


def check_range(spec: FieldDefinition, field: ExtractedField, ctx) -> list[CheckResult]:
    cid, cfg, v = "plausibility.range", spec.check_config, numeric_of(field)
    if v is None or (cfg.min_value is None and cfg.max_value is None):
        return _result(cid, Severity.BLOCK, _NA)
    if cfg.min_value is not None and v < cfg.min_value:
        return _result(cid, Severity.BLOCK, CheckOutcome.FAIL, f"{v:g} below min_value {cfg.min_value:g}",
                       threshold_ref(spec, "min_value"))
    if cfg.max_value is not None and v > cfg.max_value:
        return _result(cid, Severity.BLOCK, CheckOutcome.FAIL, f"{v:g} above max_value {cfg.max_value:g}",
                       threshold_ref(spec, "max_value"))
    return _result(cid, Severity.BLOCK, CheckOutcome.PASS)


def check_sign(spec: FieldDefinition, field: ExtractedField, ctx) -> list[CheckResult]:
    cid, v = "plausibility.sign", numeric_of(field)
    if v is None or not spec.check_config.non_negative:
        return _result(cid, Severity.BLOCK, _NA)
    if v < 0:
        return _result(cid, Severity.BLOCK, CheckOutcome.FAIL, f"{v:g} is negative", threshold_ref(spec, "non_negative"))
    return _result(cid, Severity.BLOCK, CheckOutcome.PASS)


def check_percentage(spec: FieldDefinition, field: ExtractedField, ctx) -> list[CheckResult]:
    cid, v, ref = "plausibility.percentage", numeric_of(field), "builtin:percentage_0_100"
    if v is None or spec.data_type != FieldDataType.PERCENTAGE:
        return _result(cid, Severity.BLOCK, _NA)
    if not 0 <= v <= 100:
        return _result(cid, Severity.BLOCK, CheckOutcome.FAIL, f"{v:g} outside 0-100", ref)
    return _result(cid, Severity.BLOCK, CheckOutcome.PASS, ref=ref)


def _same_period(ctx, field_id: str, period_end: str | None) -> ExtractedField | None:
    return next((r for r in ctx.record_fields if r.field_id == field_id and r.period_end == period_end), None)


def check_part_of_whole(spec: FieldDefinition, field: ExtractedField, ctx) -> list[CheckResult]:
    cid, v, whole_id = "plausibility.part_of_whole", numeric_of(field), spec.check_config.part_of
    whole = _same_period(ctx, whole_id, field.period_end) if whole_id else None
    w = numeric_of(whole) if whole else None
    if v is None or w is None or whole.canonical_unit != field.canonical_unit:
        return _result(cid, Severity.WARN, _NA)
    if v > w:
        return _result(cid, Severity.WARN, CheckOutcome.FAIL, f"part {v:g} exceeds whole {whole_id} {w:g}")
    return _result(cid, Severity.WARN, CheckOutcome.PASS)


def check_sum_identity(spec: FieldDefinition, field: ExtractedField, ctx) -> list[CheckResult]:
    cid, cfg, total = "plausibility.sum_identity", spec.check_config, numeric_of(field)
    if total is None or not cfg.sum_of or cfg.sum_target is not None or cfg.sum_target_field:
        return _result(cid, Severity.WARN, _NA)
    parts = [_same_period(ctx, pid, field.period_end) for pid in cfg.sum_of]
    if any(p is None or numeric_of(p) is None or p.canonical_unit != field.canonical_unit for p in parts):
        return _result(cid, Severity.WARN, _NA)
    vals = [numeric_of(p) for p in parts]
    s = sum(vals)
    ref = threshold_ref(spec, "sum_tolerance")
    if abs(total - s) > cfg.sum_tolerance * max(abs(total), 1e-9):
        detail = f"total {total:g} vs parts {'+'.join(f'{x:g}' for x in vals)}={s:g}"
        return _result(cid, Severity.WARN, CheckOutcome.FAIL, detail, ref)
    return _result(cid, Severity.WARN, CheckOutcome.PASS, ref=ref)


def check_less_or_equal(spec: FieldDefinition, field: ExtractedField, ctx) -> list[CheckResult]:
    cid, v = "le_of", numeric_of(field)
    if v is None:
        return _result(cid, Severity.WARN, _NA)
    checked = 0
    for other_id in spec.check_config.le_of:
        other = _same_period(ctx, other_id, field.period_end)
        o = numeric_of(other) if other else None
        if o is None or other.canonical_unit != field.canonical_unit:
            continue
        checked += 1
        if v > o:
            return _result(cid, Severity.WARN, CheckOutcome.FAIL, f"{v:g} exceeds {other_id} {o:g}")
    return _result(cid, Severity.WARN, CheckOutcome.PASS if checked else _NA)


def check_sum_to_target(spec: FieldDefinition, field: ExtractedField, ctx) -> list[CheckResult]:
    cid, cfg, own = "sum_target", spec.check_config, numeric_of(field)
    target, ref_name = cfg.sum_target, "sum_target"
    if cfg.sum_target_field:
        sibling = _same_period(ctx, cfg.sum_target_field, field.period_end)
        ok = sibling is not None and sibling.canonical_unit == field.canonical_unit
        target, ref_name = (numeric_of(sibling) if ok else None), "sum_target_field"
    if target is None or not cfg.sum_of or own is None:
        return _result(cid, Severity.WARN, _NA)
    parts = [_same_period(ctx, pid, field.period_end) for pid in cfg.sum_of]
    if any(p is None or numeric_of(p) is None or p.canonical_unit != field.canonical_unit for p in parts):
        return _result(cid, Severity.WARN, _NA)
    vals = [numeric_of(p) for p in parts] + [own]
    s, ref = sum(vals), threshold_ref(spec, ref_name)
    if abs(s - target) > cfg.sum_tolerance * max(abs(target), 1e-9):
        detail = f"parts and field {'+'.join(f'{x:g}' for x in vals)}={s:g} vs target {target:g}"
        return _result(cid, Severity.WARN, CheckOutcome.FAIL, detail, ref)
    return _result(cid, Severity.WARN, CheckOutcome.PASS, ref=ref)
