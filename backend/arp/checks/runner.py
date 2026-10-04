from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date

from arp.schemas.common import CompanyRef, SourceDocument
from arp.schemas.datapoints import (
    CheckOutcome,
    CheckResult,
    DataPointSchema,
    ExtractedField,
    FieldDataType,
    FieldDefinition,
    Severity,
    ValueState,
    is_blocking,
    is_failing,
)
from arp.schemas.review import ReasonCode

_NUMERIC = {FieldDataType.NUMBER, FieldDataType.CURRENCY_AMOUNT, FieldDataType.PERCENTAGE}


@dataclass
class CheckContext:
    company: CompanyRef
    issuer_key: str
    schema: DataPointSchema
    documents_by_id: dict[str, SourceDocument]
    record_fields: list[ExtractedField]
    history: RunHistory | None = None  # noqa: F821 -- defined in a later task


Check = Callable[[FieldDefinition, ExtractedField, CheckContext], list[CheckResult]]
ModelCheck = Callable[[FieldDefinition, ExtractedField, CheckContext], Awaitable[list[CheckResult]]]


def threshold_ref(spec: FieldDefinition, name: str) -> str:
    return f"{spec.field_id}:v{spec.version}:check_config.{name}"


def _format_result(check_id: str, outcome: CheckOutcome, detail: str = "") -> CheckResult:
    return CheckResult(check_id=check_id, layer=1, outcome=outcome, severity=Severity.BLOCK, detail=detail)


def check_format(spec: FieldDefinition, field: ExtractedField, ctx: CheckContext) -> list[CheckResult]:
    if field.value_state not in (ValueState.FOUND, ValueState.ZERO):
        return [
            _format_result("format.data_type", CheckOutcome.NOT_APPLICABLE),
            _format_result("format.allowed_values", CheckOutcome.NOT_APPLICABLE),
        ]
    v, dt = field.value, spec.data_type
    bad = ""
    if dt in _NUMERIC:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            bad = f"{dt} field holds non-numeric value {v!r}"
    elif dt == FieldDataType.BOOLEAN:
        if not isinstance(v, bool):
            bad = f"boolean field holds non-boolean value {v!r}"
    elif dt == FieldDataType.DATE:
        try:
            date.fromisoformat(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            bad = f"date field holds non-ISO value {v!r}"
    out = [_format_result("format.data_type", CheckOutcome.FAIL if bad else CheckOutcome.PASS, bad)]
    if dt == FieldDataType.ENUM:
        ok = v in (spec.allowed_values or [])
        out.append(
            _format_result(
                "format.allowed_values", CheckOutcome.PASS if ok else CheckOutcome.FAIL, "" if ok else f"{v!r} not in allowed_values"
            )
        )
    else:
        out.append(_format_result("format.allowed_values", CheckOutcome.NOT_APPLICABLE))
    return out


# Later tasks append checks to layers 2-4.
LAYERS: dict[int, list[Check]] = {1: [check_format], 2: [], 3: [], 4: []}


async def run_checks(
    spec: FieldDefinition, field: ExtractedField, ctx: CheckContext, *, model_check: ModelCheck | None = None
) -> list[CheckResult]:
    results: list[CheckResult] = []
    for layer in (1, 2, 3, 4):
        for check in LAYERS[layer]:
            results.extend(check(spec, field, ctx))
        if any(is_blocking(r) for r in results):
            return results
    if model_check is not None:
        results.extend(await model_check(spec, field, ctx))
    return results


async def check_record(
    schema: DataPointSchema, fields: list[ExtractedField], ctx: CheckContext, *, model_check: ModelCheck | None = None
) -> list[ExtractedField]:
    specs = {f.field_id: f for f in schema.fields}
    out: list[ExtractedField] = []
    for field in fields:
        spec = specs.get(field.field_id)
        if spec is None:
            out.append(field)
            continue
        checks = await run_checks(spec, field, ctx, model_check=model_check)
        update: dict = {"checks": checks}
        failing = [r for r in checks if is_failing(r)]
        if failing:
            if ReasonCode.CHECK_FAILED not in field.review_reasons:
                update["review_reasons"] = [*field.review_reasons, ReasonCode.CHECK_FAILED]
            notes = "; ".join(f"{r.check_id}: {r.detail}" for r in failing)
            update["verifier_notes"] = f"{field.verifier_notes}; {notes}" if field.verifier_notes else notes
        out.append(field.model_copy(update=update))
    return out


from arp.checks.numeric import check_caption_scale, check_number_in_span, check_row_label  # noqa: E402

LAYERS[2] = [check_number_in_span, check_caption_scale, check_row_label]
