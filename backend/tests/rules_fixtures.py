"""Schema F and rules R1..R6 from the schema-rules spec's Acceptance section."""
from __future__ import annotations

from arp.schemas.datapoints import DataPointSchema, FieldDefinition
from arp.schemas.datapoints import FieldDataType as T
from arp.schemas.rules import ComputedRule, Condition, FieldRule, LabelRule, RequiresRule, SeriesRule, ThresholdRule

# (field_id, name, type, unit, allowed_values)
_F = [
    ("ambition", "Halving target", T.BOOLEAN, None, None),
    ("pct", "Target reduction", T.PERCENTAGE, None, None),
    ("year", "Target year", T.NUMBER, None, None),
    ("nz", "Net-zero target", T.BOOLEAN, None, None),
    ("nz2050", "Net zero by 2050", T.BOOLEAN, None, None),
    ("int1", "Scope 1 intensity", T.NUMBER, "tCO2e/EURm", None),
    ("declined", "Intensity declined", T.BOOLEAN, None, None),
    ("kind", "Target type", T.ENUM, None, ["standalone", "combined"]),
    ("s1", "Scope 1 target", T.BOOLEAN, None, None),
    ("green", "Green capex", T.CURRENCY_AMOUNT, "EUR millions", None),
    ("total", "Total capex", T.CURRENCY_AMOUNT, "EUR millions", None),
    ("other", "Other capex", T.CURRENCY_AMOUNT, "EUR millions", None),
    ("share", "Green capex share", T.PERCENTAGE, None, None),
]


def schema_f(**field_overrides: dict) -> DataPointSchema:
    """Schema F; `schema_f(green={"unit": None})` overrides attributes of the field with that id."""
    fields = [
        FieldDefinition(**{
            "field_id": fid, "name": name, "description": f"{name}.", "data_type": dt, "unit": unit,
            "extraction_instructions": "Find it.", "allowed_values": allowed, **field_overrides.get(fid, {}),
        })
        for fid, name, dt, unit, allowed in _F
    ]
    return DataPointSchema(name="F", fields=fields)


def with_rules(schema: DataPointSchema, rules: dict[str, list[FieldRule]]) -> DataPointSchema:
    """Sets `rules` per field id without re-validating, so tests can build invalid schemas."""
    fields = [f.model_copy(update={"rules": rules[f.field_id]}) if f.field_id in rules else f for f in schema.fields]
    return schema.model_copy(update={"fields": fields})


def R1() -> FieldRule:
    return ThresholdRule(
        rule_id="R1", kind="threshold", when=True,
        conditions=[Condition(field="pct", op=">=", value=50), Condition(field="year", op="<=", value=2030)],
    )


def R2() -> FieldRule:
    return RequiresRule(rule_id="R2", kind="requires", when=True, field="nz", equals=True)


def R3() -> FieldRule:
    return SeriesRule(rule_id="R3", kind="series", when=True, field="int1", years=5, trend="down")


def R4() -> FieldRule:
    return LabelRule(rule_id="R4", kind="label", when=True, field="kind", not_in=["combined"])


def R5() -> FieldRule:
    return ComputedRule(rule_id="R5", kind="computed", formula="ratio_pct", inputs=["green", "total"], tolerance=1)


def R6() -> FieldRule:
    return ComputedRule(rule_id="R6", kind="computed", formula="sum", inputs=["green", "other"], tolerance=0.5)


def schema_f_with_r1_r6() -> DataPointSchema:
    return with_rules(schema_f(), {"ambition": [R1()], "nz2050": [R2()], "declined": [R3()], "s1": [R4()], "share": [R5()], "total": [R6()]})
