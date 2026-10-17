from __future__ import annotations

from arp.schemas.datapoints import DataPointSchema
from arp.schemas.rules import ComputedRule, FieldRule, LabelRule, RequiresRule, SeriesRule, ThresholdRule


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
