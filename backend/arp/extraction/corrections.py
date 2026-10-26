"""Deterministic auto-corrections applied to extracted rows before the record checks. No model calls."""

from __future__ import annotations

import re

from arp.normalise.period import resolve_period
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
    planned_ids = planned_field_ids(schema)
    for fid, spec in specs.items():
        idx = [i for i, r in enumerate(rows) if r.field_id == fid]
        filled = _period_fill([rows[i] for i in idx], spec, documents_by_id=documents_by_id,
                              fiscal_year_end=fiscal_year_end, planned_ids=planned_ids)
        for i, r in zip(idx, filled, strict=True):
            rows[i] = r
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


_YEAR = re.compile(r"\b(19|20)\d{2}\b")


def _period_fill(rows: list[ExtractedField], spec: FieldDefinition, *, documents_by_id: dict[str, SourceDocument],
                 fiscal_year_end: str | None, planned_ids: set[str]) -> list[ExtractedField]:
    """R2 for one field's rows; the whole field is needed so a fill never duplicates a period."""
    if spec.data_type not in NUMERIC:
        return rows
    todo = [r.value_state in (ValueState.FOUND, ValueState.ZERO) and r.period_end is None for r in rows]
    # candidate: (period_end, period_start, reason) or None when the row cannot be filled
    cands: list[tuple[str, str | None, str] | None] = []
    for r, t in zip(rows, todo, strict=True):
        cand = None
        if t:
            years = {m.group(0) for q in grounded_quotes(r) for m in _YEAR.finditer(q)}
            if len(years) == 1:
                (y,) = years
                p = resolve_period(y, fiscal_year_end=fiscal_year_end)
                cand = (p.end.isoformat(), p.start.isoformat(), f"The quote names only {y}.")
            elif not years and spec.field_id not in planned_ids and (end := report_period_end(r, documents_by_id)):
                cand = (end, _year_start_iso(end), f"No year in the quote; taken from the report's period end {end}.")
        cands.append(cand)
    taken = {r.period_end for r in rows if r.period_end}
    wanted = [c[0] for c in cands if c]
    out = []
    for r, t, cand in zip(rows, todo, cands, strict=True):
        if not t:
            out.append(r)
        elif cand and cand[0] not in taken and wanted.count(cand[0]) == 1:
            c = Correction(rule="period_fill", attribute="period_end", original=None, corrected=cand[0], reason=cand[2])
            out.append(r.model_copy(update={"period_end": cand[0], "period_start": cand[1],
                                            "corrections": [*r.corrections, c]}))
        elif ReasonCode.PERIOD_MISSING not in r.review_reasons:
            out.append(r.model_copy(update={"review_reasons": [*r.review_reasons, ReasonCode.PERIOD_MISSING]}))
        else:
            out.append(r)
    return out


def _year_start_iso(end: str) -> str | None:
    # A year before `end`, plus a day, as resolve_period does for a fiscal year; None if `end` is not an ISO date.
    try:
        return resolve_period(f"year ended {end}", fiscal_year_end=None).start.isoformat()
    except (ValueError, AttributeError):
        return None


# R3-R4 land in later tasks; no-ops keep the call order fixed.
def _unit_scale(rows: list[ExtractedField], schema: DataPointSchema) -> list[ExtractedField]:
    return rows


def _planned_move(rows: list[ExtractedField], schema: DataPointSchema, documents_by_id: dict[str, SourceDocument],
                  input_hashes: dict[str, str | None]) -> list[ExtractedField]:
    return rows
