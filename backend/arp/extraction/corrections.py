"""Deterministic auto-corrections applied to extracted rows before the record checks. No model calls."""

from __future__ import annotations

import re

from arp.extraction.extractor_agent import PeriodValue
from arp.normalise.period import resolve_period
from arp.normalise.units import split_unit
from arp.normalise.value import PRINTED, typed_value
from arp.schemas.common import ProvenanceInfo, SourceDocument
from arp.schemas.datapoints import (
    Alternative,
    Correction,
    DataPointSchema,
    ExtractedField,
    FieldDataType,
    FieldDefinition,
    ValueState,
)
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
    rows = [_unit_scale(r, specs[r.field_id], fiscal_year_end=fiscal_year_end) if r.field_id in specs else r
            for r in rows]
    rows = _planned_move(rows, schema, documents_by_id=documents_by_id, input_hashes=input_hashes)
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


_SCALE_WORDS = {"thousand": 1e3, "thousands": 1e3, "k": 1e3, "million": 1e6, "millions": 1e6, "mn": 1e6, "m": 1e6,
                "billion": 1e9, "billions": 1e9, "bn": 1e9, "b": 1e9}
_SCALE_ALT = "|".join(sorted(_SCALE_WORDS, key=len, reverse=True))
_SCALE_WORD = re.compile(r"\b(" + _SCALE_ALT + r")\b", re.I)


def _printed(row: ExtractedField) -> str | None:
    """The row's number as a string: the first number in raw_value_text, else the value."""
    if row.raw_value_text:
        m = PRINTED.search(row.raw_value_text)
        return m[0].replace(",", "") if m else None
    if isinstance(row.value, (int, float)) and not isinstance(row.value, bool):
        return f"{row.value:.10g}"
    return None


def _unit_scale(row: ExtractedField, spec: FieldDefinition, *, fiscal_year_end: str | None) -> ExtractedField:
    """R3: a unit whose scale word contradicts the one printed next to the value in a grounded quote."""
    quotes = grounded_quotes(row)
    printed = _printed(row)
    if (spec.data_type not in (FieldDataType.NUMBER, FieldDataType.CURRENCY_AMOUNT) or row.value_state != ValueState.FOUND
            or not quotes or printed is None or not row.unit):
        return row
    whole, _, frac = printed.partition(".")
    # Thousands separators are optional; a decimal point is not ("2,794" is not 2.794).
    number = re.sub(r"(?<=\d)(?=(?:\d{3})+$)", ",?", whole) + (r"\." + frac if frac else "")
    pattern = re.compile(r"(?<![\d.,])(" + number + r")\s{0,3}(?<![A-Za-z])(" + _SCALE_ALT + r")(?!\w)", re.I)
    hits = [m for q in quotes for m in pattern.finditer(q)]
    if len({_SCALE_WORDS[m[2].lower()] for m in hits}) != 1:
        return row
    effective = row.scale_applied if row.scale_applied is not None else split_unit(row.unit)[0]
    word = hits[0][2]
    if _SCALE_WORDS[word.lower()] == effective:
        return row

    def _like(old: str) -> str:  # the quote's word, plural and in the case of the word it replaces
        w = word.lower() + ("s" if old.lower().endswith("s") and word.lower() in ("thousand", "million", "billion") else "")
        return w.upper() if old.isupper() else w.capitalize() if old[0].isupper() else w

    if old := _SCALE_WORD.search(row.unit):
        unit = row.unit[: old.start()] + _like(old[0]) + row.unit[old.end():]
    else:
        unit = f"{row.unit} {word.lower()}"

    def _typed(u: str):
        pv = PeriodValue(value=row.value, state=row.value_state, raw_value_text=row.raw_value_text, unit_text=u,
                         period_text=row.period_text, basis_text=row.basis)
        return typed_value(spec, pv, fiscal_year_end=fiscal_year_end)

    before, after = _typed(row.unit), _typed(unit)
    reasons = [r for r in row.review_reasons if r not in before.reasons or r in after.reasons]
    reasons += [r for r in after.reasons if r not in reasons]
    notes = row.verifier_notes or ""
    for n in before.notes:
        if n not in after.notes:
            notes = notes.replace(n, "")
    notes = " ".join([*notes.split(), *(n for n in after.notes if n not in before.notes)]) or None
    c = Correction(rule="unit_scale", attribute="unit", original=row.unit, corrected=unit,
                   reason=f'The quote says "{word}" next to {hits[0][1]}.')
    return row.model_copy(update={
        "unit": unit, "canonical_value": after.canonical_value, "canonical_unit": after.canonical_unit,
        "scale_applied": after.scale_applied, "review_reasons": reasons, "verifier_notes": notes,
        "corrections": [*row.corrections, c]})


def _amount(row: ExtractedField):
    return row.canonical_value if row.canonical_value is not None else row.value


def _planned_move(rows: list[ExtractedField], schema: DataPointSchema, *, documents_by_id: dict[str, SourceDocument],
                  input_hashes: dict[str, str | None]) -> list[ExtractedField]:
    """R4: a figure for a period after the report's period end is planned, not actual."""
    specs = {f.field_id: f for f in schema.fields}
    live = (ValueState.FOUND, ValueState.ZERO)
    rows = list(rows)
    for i, r in enumerate(rows):
        spec = specs.get(r.field_id)
        planned = specs.get(spec.planned_field_id) if spec and spec.planned_field_id else None
        end = report_period_end(r, documents_by_id)
        if not planned or r.value_state not in live or not r.period_end or not end or r.period_end <= end:
            continue
        reason = f"Period {r.period_end} is after the report's period end {end}, so it is a planned figure."
        j = next((j for j, p in enumerate(rows)
                  if p.field_id == planned.field_id and p.period_end == r.period_end and p.value_state in live), None)
        if j is None:
            c = Correction(rule="planned_move", attribute="field_id", original=r.field_id,
                           corrected=planned.field_id, reason=reason)
            prov = r.provenance or ProvenanceInfo()
            rows[i] = r.model_copy(update={
                "field_id": planned.field_id, "field_name": planned.name, "input_hash": input_hashes.get(planned.field_id),
                "provenance": prov.model_copy(update={"field_version": planned.version}),
                "corrections": [*r.corrections, c]})
            continue
        c = Correction(rule="planned_move", attribute="value", original=r.value, corrected=None, reason=reason)
        rows[i] = r.model_copy(update={"value": None, "value_state": ValueState.NOT_FOUND, "canonical_value": None,
                                       "corrections": [*r.corrections, c]})
        a, b = _amount(r), _amount(rows[j])
        if not (isinstance(a, (int, float)) and isinstance(b, (int, float))) or abs(a - b) > 0.01 * abs(b):
            alt = Alternative(value=r.value, raw_value_text=r.raw_value_text, source="planned_move", citations=r.citations)
            rows[j] = rows[j].model_copy(update={"alternatives": [*rows[j].alternatives, alt]})
    return rows
