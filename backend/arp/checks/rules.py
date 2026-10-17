from __future__ import annotations

import operator
from typing import TYPE_CHECKING

from arp.schemas.datapoints import (
    CheckOutcome,
    CheckResult,
    DataPointSchema,
    ExtractedField,
    FieldDefinition,
    Severity,
    ValueState,
)
from arp.schemas.rules import ComputedRule, FieldRule, LabelRule, RequiresRule, SeriesRule, ThresholdRule, rule_inputs

if TYPE_CHECKING:
    from arp.checks.runner import CheckContext


def format_value(v: bool | float | str | None) -> str:
    """Booleans as YES/NO, whole numbers without a decimal point, anything else as stored."""
    if isinstance(v, bool):
        return "YES" if v else "NO"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def rule_sentence(rule: FieldRule, field_id: str, schema: DataPointSchema) -> str:
    names = {f.field_id: f.name for f in schema.fields}
    n = lambda fid: names.get(fid, fid)  # noqa: E731 - unknown ids fall back to the id
    if isinstance(rule, RequiresRule):
        body = f"needs {n(rule.field)} to be {format_value(rule.equals)}."
    elif isinstance(rule, ThresholdRule):
        body = "needs " + " and ".join(f"{n(c.field)} {c.op} {format_value(c.value)}" for c in rule.conditions) + "."
    elif isinstance(rule, SeriesRule):
        trend = {"down": ", falling", "up": ", rising"}.get(rule.trend, "")
        body = f"needs {n(rule.field)} for {rule.years} years up to the report year{trend}."
    elif isinstance(rule, LabelRule):
        body = f"{n(rule.field)} must not be " + " or ".join(rule.not_in) + "."
    elif isinstance(rule, ComputedRule):
        ins = [n(i) for i in rule.inputs]
        expr = f"{ins[0]} ÷ {ins[1]} × 100" if rule.formula == "ratio_pct" else " + ".join(ins)
        body = f"{n(field_id)} should equal {expr}, within {format_value(rule.tolerance)}."
    if rule.when is None:
        return body[0].upper() + body[1:]
    return f"When {n(field_id)} is {format_value(rule.when)}: {body}"


_FOUND = (ValueState.FOUND, ValueState.ZERO)
_OPS = {">=": operator.ge, "<=": operator.le, ">": operator.gt, "<": operator.lt, "=": operator.eq}


def report_year(ctx: CheckContext) -> int | None:
    """The latest period-end year in the run's period plans, or None without one."""
    years = [int(d.period_plan.current[:4]) for d in ctx.documents_by_id.values() if d.period_plan and d.period_plan.current]
    return max(years, default=None)


def _num(r: ExtractedField) -> float | None:
    v = r.canonical_value if r.canonical_value is not None else r.value
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return 0.0 if r.value_state == ValueState.ZERO else None


def _found(r: ExtractedField | None, numeric: bool = False) -> bool:
    """Spec "Not found" inverted; `numeric` also needs a number to compare."""
    return r is not None and r.value_state in _FOUND and r.grounded and (not numeric or _num(r) is not None)


def _shown(r: ExtractedField) -> bool | float | str | None:
    return 0 if r.value_state == ValueState.ZERO and r.value is None else r.value


def _same(a, b) -> bool:
    """Typed equality: a bool only equals a bool and a string only a string."""
    if isinstance(a, bool) or isinstance(b, bool) or isinstance(a, str) or isinstance(b, str):
        return type(a) is type(b) and a == b
    return a == b


def _pick(fid: str, row: ExtractedField, ctx: CheckContext) -> ExtractedField | None:
    """The other field's row for this checked row (spec "Periods", order 1-4), or None."""
    rows = [r for r in ctx.record_fields if r.field_id == fid]
    same = [r for r in rows if r.period_end == row.period_end]
    if same:
        return same[0]
    if len(rows) == 1:
        return rows[0]
    dated = [r for r in rows if r.period_end]
    if row.period_end is None and dated:
        return max(dated, key=lambda r: r.period_end)
    return None


def _cited(name: str, r: ExtractedField) -> str:
    page = r.citations[0].page if r.citations else None
    return f"{name} = {format_value(_shown(r))}" + (f" (p. {page})" if page is not None else "")


def _found_part(ids: list[str], picked: dict, names: dict[str, str], numeric: bool) -> tuple[list[str], list[str]]:
    """`<name> = <value> (p. N)` for found inputs, and the names of missing ones, in rule order."""
    found = [_cited(names[i], picked[i]) for i in ids if _found(picked[i], numeric)]
    missing = [names[i] for i in ids if not _found(picked[i], numeric)]
    return found, missing


def _detail(found: list[str], missing: list[str], tail: str = "") -> str:
    parts = [f"Found {', '.join(found)}." if found else "", f"Not found: {', '.join(missing)}." if missing else "", tail]
    return " ".join(p for p in parts if p)


def _eval_series(rule: SeriesRule, ctx: CheckContext, names: dict[str, str]) -> tuple[bool, str]:
    year = report_year(ctx)
    if year is None:
        return False, "Report year unknown."
    window = range(year - rule.years + 1, year + 1)
    by_year: dict[int, ExtractedField] = {}
    for r in ctx.record_fields:
        if r.field_id == rule.field and r.period_end:
            by_year.setdefault(int(r.period_end[:4]), r)  # first row for a year wins
    rows = {y: by_year.get(y) for y in window}
    have = [y for y in window if _found(rows[y], numeric=True)]
    missing = [y for y in window if y not in have]
    found = [f"{y} = {format_value(_shown(rows[y]))}" for y in have]
    missing_s = [str(y) for y in missing]
    for part in (found, missing_s):  # the name leads only the first year: "Scope 1 intensity 2020 = 10, 2021 = 9"
        if part:
            part[0] = f"{names[rule.field]} {part[0]}"
    units_differ = len({rows[y].canonical_unit for y in have}) > 1
    ok = not missing and not units_differ
    if ok and rule.trend != "none":
        first, last = _num(rows[window[0]]), _num(rows[window[-1]])
        ok = last < first if rule.trend == "down" else last > first
    return ok, _detail(found, missing_s, "Units differ." if units_differ else "")


def _eval_computed(rule: ComputedRule, row: ExtractedField, picked: dict, names: dict[str, str], field_id: str) -> tuple[bool, str]:
    found, missing = _found_part(rule.inputs, picked, names, numeric=True)
    if _num(row) is None:
        missing.append(names[field_id])
    else:
        found.append(_cited(names[field_id], row))
    if missing:
        return False, _detail(found, missing)
    ins = [picked[i] for i in rule.inputs]
    group = ins if rule.formula == "ratio_pct" else [*ins, row]
    if len({r.canonical_unit for r in group}) > 1:
        return False, _detail(found, [], "Units differ.")
    if rule.formula == "ratio_pct":
        if _num(ins[1]) == 0:
            return False, _detail(found, [], "Cannot divide by zero.")
        expected = _num(ins[0]) / _num(ins[1]) * 100
    else:
        expected = sum(_num(r) for r in ins)
    if abs(_num(row) - expected) <= rule.tolerance:
        return True, ""
    return False, f"{_detail(found, [])} Expected {format_value(round(expected, 2))}."


def _eval(rule: FieldRule, row: ExtractedField, ctx: CheckContext, names: dict[str, str], field_id: str) -> tuple[bool, str]:
    """(passed, found part) for a rule that applies to this row."""
    if isinstance(rule, SeriesRule):
        return _eval_series(rule, ctx, names)
    ids = rule_inputs(rule)
    picked = {i: _pick(i, row, ctx) for i in ids}
    if isinstance(rule, ComputedRule):
        return _eval_computed(rule, row, picked, names, field_id)
    found, missing = _found_part(ids, picked, names, numeric=isinstance(rule, ThresholdRule))
    if missing:
        return False, _detail(found, missing)
    if isinstance(rule, ThresholdRule):
        ok = all(_OPS[c.op](_num(picked[c.field]), c.value) for c in rule.conditions)
    elif isinstance(rule, RequiresRule):
        ok = _same(_shown(picked[rule.field]), rule.equals)
    else:  # LabelRule
        v = _shown(picked[rule.field])
        ok = not (isinstance(v, str) and v in rule.not_in)
    return ok, _detail(found, [])


def evaluate_rules(spec: FieldDefinition, row: ExtractedField, ctx: CheckContext) -> list[CheckResult]:
    """One WARN result per rule of `spec` for this row; FAIL details follow the spec's "Running rules"."""
    names = {f.field_id: f.name for f in ctx.schema.fields}
    out = []
    for rule in spec.rules:
        outcome, detail = CheckOutcome.NOT_APPLICABLE, ""
        if _found(row) and (rule.when is None or _same(_shown(row), rule.when)):
            ok, part = _eval(rule, row, ctx, names, spec.field_id)
            outcome = CheckOutcome.PASS if ok else CheckOutcome.FAIL
            detail = "" if ok else f"{rule_sentence(rule, spec.field_id, ctx.schema)} Failed. {part}"
        out.append(CheckResult(
            check_id=f"rule.{rule.rule_id}", layer=3, outcome=outcome, severity=Severity.WARN, detail=detail,
            threshold_ref=f"{spec.field_id}:v{spec.version}:rules.{rule.rule_id}",
        ))
    return out
