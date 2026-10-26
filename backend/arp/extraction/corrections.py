"""Deterministic auto-corrections applied to extracted rows before the record checks. No model calls."""

from __future__ import annotations

import re

from arp.schemas.common import SourceDocument
from arp.schemas.datapoints import Correction, DataPointSchema, ExtractedField, FieldDataType, FieldDefinition, ValueState
from arp.schemas.review import ReasonCode

NUMERIC = {FieldDataType.NUMBER, FieldDataType.CURRENCY_AMOUNT, FieldDataType.PERCENTAGE}


def grounded_quotes(row: ExtractedField) -> list[str]:
    return [c.quote for c in row.citations if c.grounded]


def report_period_end(row: ExtractedField, documents_by_id: dict[str, SourceDocument]) -> str | None:
    for c in row.citations:
        doc = documents_by_id.get(c.doc_id)
        if doc and doc.period_plan and doc.period_plan.current:
            return doc.period_plan.current
    return None


def planned_field_ids(schema: DataPointSchema) -> set[str]:
    return {f.planned_field_id for f in schema.fields if f.planned_field_id}


def apply_corrections(
    schema: DataPointSchema,
    fields: list[ExtractedField],
    *,
    documents_by_id: dict[str, SourceDocument],
    fiscal_year_end: str | None,
    input_hashes: dict[str, str | None],
) -> list[ExtractedField]:
    """Return corrected copies of `fields` (rules R1-R4 in order); the inputs are never mutated."""
    specs = {f.field_id: f for f in schema.fields}
    rows = [_label_map(r, specs[r.field_id]) if r.field_id in specs else r for r in fields]
    rows = _period_fill(rows, schema, documents_by_id, fiscal_year_end)
    rows = _unit_scale(rows, schema)
    rows = _planned_move(rows, schema, documents_by_id, input_hashes)
    return [
        r.model_copy(update={"review_reasons": [*r.review_reasons, ReasonCode.AUTO_CORRECTED]})
        if r.corrections and ReasonCode.AUTO_CORRECTED not in r.review_reasons
        else r
        for r in rows
    ]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _label_map(row: ExtractedField, spec: FieldDefinition) -> ExtractedField:
    allowed = spec.allowed_values or []
    if (spec.data_type != FieldDataType.ENUM or row.value_state != ValueState.FOUND
            or not isinstance(row.value, str) or row.value in allowed):
        return row
    norm = _norm(row.value)
    exact = [a for a in allowed if _norm(a) == norm]
    tokens = set(norm.split("_")) - {""}
    sub = [a for a in allowed if (t := set(_norm(a).split("_")) - {""}) and t <= tokens]
    pick = exact[0] if len(exact) == 1 else sub[0] if len(sub) == 1 else None
    if pick is None:
        return row
    c = Correction(rule="label_map", attribute="value", original=row.value, corrected=pick,
                   reason=f'"{row.value}" maps to the allowed value "{pick}".')
    return row.model_copy(update={"value": pick, "corrections": [*row.corrections, c]})


# R2-R4 land in later tasks; no-ops keep the call order fixed.
def _period_fill(rows, schema, documents_by_id, fiscal_year_end):
    return rows


def _unit_scale(rows, schema):
    return rows


def _planned_move(rows, schema, documents_by_id, input_hashes):
    return rows
