"""Layer 2 checks: numbers against the cited span, caption scale, table row label (E35).

Deferred: column-label checks and table-caption lookup through ``Citation.table_ref``.
The parser gives no table structure (``table_ref`` is always None), so captions are
read from the text before the span.
"""

from __future__ import annotations

import math
import re

from arp.normalise.units import lookup_scale
from arp.schemas.datapoints import (
    CheckOutcome,
    CheckResult,
    ExtractedField,
    FieldDataType,
    FieldDefinition,
    Severity,
    ValueState,
)

_NUMERIC = {FieldDataType.NUMBER, FieldDataType.CURRENCY_AMOUNT, FieldDataType.PERCENTAGE}
_SPACES = "    "
# One separator at a time, so a table row's double-space column gap splits numbers.
_NUM_RE = re.compile(rf"[(\-−]?\d+(?:[.,'{_SPACES}]\d+)*\)?")
_CURRENCY = re.compile(r"\b(?:USD|EUR|GBP|CHF|JPY|CNY|AUD|CAD)\b|[$€£¥]")
_IN_SCALE = re.compile(r"\bin\s+(\S+)", re.I)
_PAREN = re.compile(r"\(([^)]*)\)")


def parse_number(text: str) -> float | None:
    s = text.strip()
    neg = s.startswith("(") and s.endswith(")")
    s = re.sub(rf"[^\d.,\-−'{_SPACES}]", "", s)
    s = re.sub(rf"['{_SPACES}]", "", s)
    if s[:1] in "-−":
        neg, s = True, s[1:]
    if not s or not s[0].isdigit() or not s[-1].isdigit():
        return None
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("," if dec == "." else ".", "").replace(dec, ".")
    elif "," in s:
        s = s.replace(",", "") if s.count(",") > 1 or re.fullmatch(r"\d+,\d{3}", s) else s.replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def numbers_in(text: str) -> list[float]:
    return [v for m in _NUM_RE.finditer(text) if (v := parse_number(m.group())) is not None]


def _candidates(text: str) -> list[float]:
    """Every parse of each match and of each run of its space-separated pieces ("1 4,210" -> 14210, 4210, 1)."""
    out = []
    for m in _NUM_RE.finditer(text):
        g = m.group()
        seps = [i for i, ch in enumerate(g) if ch in _SPACES]
        cuts = [0, *[i + 1 for i in seps]]
        ends = [*seps, len(g)]
        for a in cuts:
            for b in ends:
                if b > a and (v := parse_number(g[a:b])) is not None:
                    out.append(v)
    return out


def _line_scale(line: str) -> float | None:
    words = [m.group(1) for m in _IN_SCALE.finditer(line)]
    for p in _PAREN.finditer(line):
        words += p.group(1).split()
    for w in words:
        hit = lookup_scale(w.strip(".,;:()"))
        if hit and (not hit[1] or _CURRENCY.search(line)):
            return hit[0]
    return None


def caption_scale(doc_text: str, char_start: int, window: int = 600) -> tuple[float, str] | None:
    for line in reversed(doc_text[max(0, char_start - window) : char_start].splitlines()):
        factor = _line_scale(line)
        if factor is not None:
            return factor, line.strip()
    return None


def _result(check_id: str, severity: Severity, outcome: CheckOutcome, detail: str = "") -> list[CheckResult]:
    return [CheckResult(check_id=check_id, layer=2, outcome=outcome, severity=severity, detail=detail)]


def _grounded(field: ExtractedField):
    return [c for c in field.citations if c.grounded and c.span_text]


def check_number_in_span(spec: FieldDefinition, field: ExtractedField, ctx) -> list[CheckResult]:
    cid, na = "numeric.in_span", CheckOutcome.NOT_APPLICABLE
    cits = _grounded(field)
    if spec.data_type not in _NUMERIC or field.value_state != ValueState.FOUND or not cits:
        return _result(cid, Severity.BLOCK, na)
    expected = parse_number(field.raw_value_text or "")
    if expected is None:
        if isinstance(field.value, bool) or not isinstance(field.value, (int, float)):
            return _result(cid, Severity.BLOCK, na)
        expected = float(field.value)
    ok = any(math.isclose(abs(expected), abs(n), rel_tol=1e-9) for c in cits for n in _candidates(c.span_text))
    return _result(cid, Severity.BLOCK, CheckOutcome.PASS if ok else CheckOutcome.FAIL,
                   "" if ok else f"value {expected:g} not in grounded span")


def check_caption_scale(spec: FieldDefinition, field: ExtractedField, ctx) -> list[CheckResult]:
    cid, na = "numeric.caption_scale", CheckOutcome.NOT_APPLICABLE
    cits = _grounded(field)
    if spec.data_type == FieldDataType.PERCENTAGE or not cits or cits[0].char_start is None:
        return _result(cid, Severity.WARN, na)
    doc = ctx.documents_by_id.get(cits[0].doc_id)
    cap = caption_scale(doc.full_text, cits[0].char_start) if doc else None
    if cap is None:
        return _result(cid, Severity.WARN, na)
    factor, text = cap
    applied = field.scale_applied or 1.0
    if factor == applied:
        return _result(cid, Severity.WARN, CheckOutcome.PASS)
    return _result(cid, Severity.WARN, CheckOutcome.FAIL,
                   f"caption {text!r} implies scale {factor:g}, scale_applied is {applied:g}")


def check_row_label(spec: FieldDefinition, field: ExtractedField, ctx) -> list[CheckResult]:
    cid, na = "numeric.row_label", CheckOutcome.NOT_APPLICABLE
    cits = [c for c in _grounded(field) if c.char_start is not None and c.char_end is not None]
    doc = ctx.documents_by_id.get(cits[0].doc_id) if cits else None
    if doc is None:
        return _result(cid, Severity.WARN, na)
    t, c = doc.full_text, cits[0]
    line = t[t.rfind("\n", 0, c.char_start) + 1 : (t.find("\n", c.char_end) if t.find("\n", c.char_end) >= 0 else len(t))]
    if len(numbers_in(line)) < 2:
        return _result(cid, Severity.WARN, na)
    low = line.casefold()
    words = [k.casefold() for k in spec.seed_keywords] + [w.casefold() for w in re.findall(r"[^\W\d_]{4,}", spec.name)]
    if any(w in low for w in words):
        return _result(cid, Severity.WARN, CheckOutcome.PASS)
    return _result(cid, Severity.WARN, CheckOutcome.FAIL, f"row {line.strip()!r} has no label matching {spec.name!r}")
