"""Turn an extractor PeriodValue (text as printed) into a typed, canonical value."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from arp.decision.parsing import to_number
from arp.extraction.extractor_agent import PeriodValue
from arp.normalise import fx
from arp.normalise.locale import Decimal, parse_number
from arp.normalise.period import (
    Qualifier,
    ResolvedPeriod,
    detect_qualifiers,
    normalise_basis,
    reported_precision,
    resolve_period,
)
from arp.normalise.units import convert, lookup_scale, lookup_unit, split_unit
from arp.schemas.datapoints import FieldDataType, FieldDefinition, ValueState
from arp.schemas.review import ReasonCode

NUMERIC = {FieldDataType.NUMBER, FieldDataType.CURRENCY_AMOUNT, FieldDataType.PERCENTAGE}
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
PRINTED = re.compile(r"\d[\d.,]*\d|\d")
_RAW_SCALE = re.compile(r"\d[\d,]*(?:\.\d+)?\s*([A-Za-z']+)(?![\w²³])")


@dataclass(frozen=True)
class TypedValue:
    value: str | float | bool | None
    value_state: ValueState
    unit: str | None
    canonical_value: float | None
    canonical_unit: str | None
    scale_applied: float | None
    period_text: str | None
    period_start: str | None
    period_end: str | None
    basis: str | None
    qualifiers: list[str]
    reported_precision: int | None
    fx_rate: float | None
    fx_rate_ref: str | None
    reasons: list[ReasonCode]
    notes: list[str]


class _CheckFailed(Exception):
    pass


def _raw_scale(raw: str | None) -> tuple[float, bool] | None:
    for m in _RAW_SCALE.finditer(raw or ""):
        if hit := lookup_scale(m[1]):
            return hit
    return None


def _split(text: str) -> tuple[float, bool, str | None]:
    """split_unit, retried without "in"/"of"/brackets/commas (a header like "USD, in thousands");
    a lone scale word gives no base unit."""
    scale, amb, base = split_unit(text)
    if lookup_unit(base) is None:
        cleaned = re.sub(r"[(),]|\b(?:in|of)\b", " ", text).strip()
        if hit := lookup_scale(cleaned):
            return hit[0], hit[1], None
        s2, a2, b2 = split_unit(cleaned)
        if lookup_unit(b2) is not None:
            return s2, a2, b2
    return scale, amb, base or None


def unit_from_raw(raw: str | None) -> str | None:
    """Unit text read around a number in raw_value_text: "12.5%" -> "%", "$1.2bn" -> "$ bn",
    "1,234 thousand tonnes" -> "thousand tonnes". Longest readable run of words wins."""
    for m in _NUMBER.finditer(raw or ""):
        before = raw[: m.start()].split()
        prefix = before[-1] if before and lookup_unit(before[-1]) is not None else ""
        words = raw[m.end() :].replace("%", " % ").split()
        for k in range(len(words), -1, -1):
            text = " ".join(([prefix] if prefix else []) + words[:k])
            if not text:
                continue
            _, _, base = _split(text)
            if base is not None and lookup_unit(base) is not None:
                return text
    return None


def _canonical(field: FieldDefinition, value: float, pv: PeriodValue, end: date | None):
    """(canonical_value, canonical_unit, scale_applied, FxRate | None); raises _CheckFailed."""
    unit_text = pv.unit_text or unit_from_raw(pv.raw_value_text)
    unit_scale, unit_amb, base = _split(unit_text) if unit_text else (1.0, False, None)
    raw = _raw_scale(pv.raw_value_text)
    if unit_scale != 1.0 and raw and raw[0] != unit_scale:
        raise _CheckFailed("scale stated twice and differs")
    scale, amb = (unit_scale, unit_amb) if unit_scale != 1.0 else (raw or (1.0, False))
    if amb:
        raise _CheckFailed(f"ambiguous scale in {unit_text if unit_scale != 1.0 else pv.raw_value_text!r}")
    src = lookup_unit(base) if base else None
    if src and src.ambiguous:
        raise _CheckFailed(f"ambiguous unit {base!r}")
    amount = value * scale
    if field.unit is None:  # no conversion: only a known factor-1 unit is renamed to its canonical code ("€" -> "EUR")
        return amount, src.canonical if src and src.factor == 1 else base, scale, None
    if base is None:
        raise _CheckFailed(f"no unit stated or readable in the raw text; cannot convert to {field.unit}")

    c = convert(amount, base, field.unit)
    rate = None
    if c.reason == "needs_fx":
        dst = lookup_unit(split_unit(field.unit)[2])
        if end is None:
            raise _CheckFailed(f"no period end to pick an FX rate for {src.canonical}->{dst.canonical}")
        in_src = convert(amount, base, src.canonical).value
        in_dst, rate = fx.convert_amount(in_src, src.canonical, dst.canonical, end.year)
        if rate is None:
            missing = next(x for x in (src.canonical, dst.canonical) if x != "USD" and fx.rate(x, "USD", end.year) is None)
            raise _CheckFailed(f"no FX rate {missing} {end.year} in {fx.FX_TABLE}")
        c = convert(in_dst, dst.canonical, field.unit)
    if c.ambiguous:
        raise _CheckFailed(f"ambiguous unit {unit_text!r} or {field.unit!r}")
    if c.value is None:
        raise _CheckFailed(f"cannot convert {unit_text!r} to {field.unit!r} ({c.reason})")
    return c.value, field.unit, scale, rate


def typed_value(
    field: FieldDefinition, pv: PeriodValue, *, fiscal_year_end: str | None, planned: set[str] | None = None,
    decimal: Decimal | None = None,
) -> TypedValue:
    period = resolve_period(pv.period_text, fiscal_year_end=fiscal_year_end)
    if period.end is None and planned and pv.planned_period_end in planned:
        end = date.fromisoformat(pv.planned_period_end)
        period = ResolvedPeriod(None, end)
    qualifiers = [str(q) for q in detect_qualifiers(pv.raw_value_text, pv.period_text, pv.basis_text)]
    if period.fye_assumed:
        qualifiers.append(str(Qualifier.FISCAL_YEAR_END_ASSUMED))

    value, state = pv.value, pv.state
    if state == ValueState.ZERO and value is None:
        value = 0.0
    if state == ValueState.FOUND and value is None:
        state = ValueState.NOT_FOUND
    reasons: list[ReasonCode] = []
    notes: list[str] = []
    if field.data_type in NUMERIC and isinstance(value, str):
        # A numeric field returned as text ("1,234"): parse it, or say why not -- never skip silently.
        if (parsed := to_number(value, decimal=decimal)) is None:
            reasons.append(ReasonCode.CHECK_FAILED)
            notes.append(f"numeric field returned non-numeric text {value!r}")
        else:
            value = parsed
    text = pv.value if isinstance(pv.value, str) else pv.raw_value_text
    # The string as printed: the typed float no longer shows whether "1,234" was 1234 or 1.234.
    m = PRINTED.search(text) if field.data_type in NUMERIC and text else None
    if m and parse_number(m[0], decimal)[1]:
        reasons.append(ReasonCode.NUMBER_LOCALE_AMBIGUOUS)
        notes.append(f"{m[0]!r} is a thousands group or a decimal; read under the point convention")
    numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
    if state == ValueState.FOUND and numeric and value == 0:
        state = ValueState.ZERO

    canonical = canonical_unit = scale = rate = None
    if field.data_type in NUMERIC and numeric:
        try:
            canonical, canonical_unit, scale, rate = _canonical(field, float(value), pv, period.end)
        except _CheckFailed as e:
            reasons.append(ReasonCode.CHECK_FAILED)
            notes.append(str(e))

    return TypedValue(
        value=value,
        value_state=state,
        unit=pv.unit_text,
        canonical_value=canonical,
        canonical_unit=canonical_unit,
        scale_applied=scale,
        period_text=pv.period_text,
        period_start=period.start.isoformat() if period.start else None,
        period_end=period.end.isoformat() if period.end else None,
        basis=normalise_basis(pv.basis_text) or pv.basis_text,
        qualifiers=qualifiers,
        reported_precision=reported_precision(pv.raw_value_text),
        fx_rate=rate.rate if rate else None,
        fx_rate_ref=rate.ref if rate else None,
        reasons=reasons,
        notes=notes,
    )
