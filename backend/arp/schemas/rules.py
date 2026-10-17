from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

Scalar = bool | str | float


class _RuleBase(BaseModel):
    rule_id: str
    when: Scalar | None = Field(default=None, description="Applies only when the checked field has this value; empty = whenever found.")


class Condition(BaseModel):
    field: str
    op: Literal[">=", "<=", ">", "<", "="]
    value: float


class RequiresRule(_RuleBase):
    kind: Literal["requires"]
    field: str
    equals: Scalar


class ThresholdRule(_RuleBase):
    kind: Literal["threshold"]
    conditions: list[Condition] = Field(min_length=1)


class SeriesRule(_RuleBase):
    kind: Literal["series"]
    field: str
    years: int
    trend: Literal["none", "down", "up"] = "none"

    @model_validator(mode="after")
    def _years_in_range(self) -> SeriesRule:
        if not 1 <= self.years <= 5:
            raise ValueError(f"rule {self.rule_id}: years must be between 1 and 5")
        return self


class LabelRule(_RuleBase):
    kind: Literal["label"]
    field: str
    not_in: list[str] = Field(min_length=1)


class ComputedRule(_RuleBase):
    kind: Literal["computed"]
    formula: Literal["ratio_pct", "sum"]
    inputs: list[str]
    tolerance: float = 0

    @model_validator(mode="after")
    def _shape(self) -> ComputedRule:
        if self.tolerance < 0:
            raise ValueError(f"rule {self.rule_id}: tolerance must not be negative")
        if len(self.inputs) != 2 if self.formula == "ratio_pct" else len(self.inputs) < 2:
            raise ValueError(f"rule {self.rule_id}: {self.formula} needs {'exactly 2' if self.formula == 'ratio_pct' else 'at least 2'} inputs")
        return self


FieldRule = Annotated[RequiresRule | ThresholdRule | SeriesRule | LabelRule | ComputedRule, Field(discriminator="kind")]


def rule_inputs(rule: FieldRule) -> list[str]:
    """Field ids the rule reads, in the order it names them."""
    if isinstance(rule, ThresholdRule):
        ids = [c.field for c in rule.conditions]
    elif isinstance(rule, ComputedRule):
        ids = rule.inputs
    else:
        ids = [rule.field]
    return list(dict.fromkeys(ids))
