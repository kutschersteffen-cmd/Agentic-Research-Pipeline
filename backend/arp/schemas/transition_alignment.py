from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, PrivateAttr


class BenchmarkOut(BaseModel):
    value: float
    unit: str
    method: str
    citation: str
    url: str | None
    licence: str


class RndTestDef(BaseModel):
    id: str
    label: str
    numerator: str
    denominator: str
    value: float
    unit: str
    citation: str


class RedlineDef(BaseModel):
    id: str
    label: str
    fact: str
    citation: str


class SectorBenchmarksOut(BaseModel):
    sector: str
    isic_prefixes: list[str]
    capex: BenchmarkOut
    rnd_tests: list[RndTestDef]
    redlines: list[RedlineDef]


class ScenarioGroupOut(BaseModel):
    group: str
    citation: str
    prices: dict[int, float]


class BenchmarksOut(BaseModel):
    version: int
    licence_note: str
    sectors: list[SectorBenchmarksOut]  # in file order
    scenario_prices: list[ScenarioGroupOut]


class ShareOut(BaseModel):
    value: float
    source: Literal["disclosed", "computed from amounts"]
    fact_ids: list[int]


class AmountOut(BaseModel):
    field_id: str
    year: int
    shown: str
    fact_id: int
    citation: str | None


class RndResultOut(BaseModel):
    id: str
    label: str
    used: float | None
    rule: str | None
    benchmark: float
    ratio: float | None
    ratio_shown: str | None
    not_scored: str | None
    fact_ids: list[int]


class RedlineOut(BaseModel):
    id: str
    label: str
    status: Literal["breached", "not breached", "no disclosure"]
    text: str
    citation: str | None
    fact_id: int | None
    source: str


class CapexOut(BaseModel):
    reporting_year: int | None
    share_ry: ShareOut | None
    share_ry1: ShareOut | None
    share_used: float | None
    share_used_shown: str | None
    rule: str | None
    benchmark: BenchmarkOut
    ratio: float | None
    ratio_shown: str | None
    not_scored: str | None
    headline: str
    amounts: list[AmountOut]
    rnd_tests: list[RndResultOut]
    redlines: list[RedlineOut]
    licence_note: str


class B02Out(BaseModel):
    met: bool
    text: str
    fact_ids: list[int] = []  # the facts this result used (b: status, year; c: saving; d: needed, allocated)


class BarrierOut(BaseModel):
    code: str
    region: str
    rating: str | None
    basis: str | None
    evidence: str
    values: list[dict]  # the cell's counted values, as the barrier API serves them


class ActLeverOut(BaseModel):
    wording: str
    citation: str


class ActionOut(BaseModel):
    key: str
    action_id: str | None
    act_lever: ActLeverOut | None
    text: str
    status: str | None
    year: int | None
    region: str | None
    citation: str | None
    timeframe: str | None
    b02: dict[str, B02Out]  # "b", "c", "d"
    barriers: list[BarrierOut]
    note: str | None
    fact_ids: list[int]


class ComparisonOut(BaseModel):
    code: str
    region: str
    assumption: str | None
    evidence: str
    gap: str | None
    reason: str | None


class ScenarioOut(BaseModel):
    region: str
    year: int | None
    scenario: str | None
    assumption: str | None
    gap: str | None
    reason: str | None


class AssumptionOut(BaseModel):
    kind: str
    region: str | None
    year: int | None
    citation: str | None
    fact_id: int
    comparisons: list[ComparisonOut]
    scenario: list[ScenarioOut] = []


class TargetOut(BaseModel):
    key: str
    scope: str | None
    pct: float | None
    year: int | None
    base_year: int | None
    base_emissions_shown: str | None
    kind: Literal["past", "running"] | None
    ratio: str | None
    score: float | None
    reason: str | None
    citation: str | None
    fact_ids: list[int]
    _gap: Decimal | None = PrivateAttr(default=None)  # E_base x pct / 100 in tCO2e, for coverage; not served


class TargetProgressOut(BaseModel):
    score: float
    text: str


class CoverageActionOut(BaseModel):
    key: str
    saving_shown: str | None
    summed: bool
    reason: str | None


class CoverageOut(BaseModel):
    target_key: str | None
    percent: float | None
    text: str | None
    actions: list[CoverageActionOut]
    reason: str | None
    _covered: Decimal | None = PrivateAttr(default=None)  # summed savings in tCO2e/yr, for the flags; not served


class PhaseoutOut(BaseModel):
    key: str
    activity: str | None
    share: float | None
    year: int | None
    method: str | None
    share_points: int | None
    date_points: int | None
    score: float | None
    reason: str | None
    timeline_text: str
    note: str | None
    citation: str | None
    fact_ids: list[int]


class FlagOut(BaseModel):
    id: str
    title: str
    state: Literal["raised", "clear", "not checked"]
    text: str
    cite: str
    fact_ids: list[int]


class PlanOut(BaseModel):
    regions: list[str]
    actions: list[ActionOut]
    b02a: B02Out | None
    assumptions: list[AssumptionOut]


class TransitionOut(BaseModel):
    in_scope: bool
    reason: str | None
    sector: str | None
    benchmarks_version: int
    rule_book_version: int
    capex: CapexOut | None
    regions: list[str] = []
    actions: list[ActionOut] = []
    b02a: B02Out | None = None
    assumptions: list[AssumptionOut] = []
    targets: list[TargetOut] = []
    target_progress: TargetProgressOut | None = None
    coverage: CoverageOut | None = None
    phaseouts: list[PhaseoutOut] = []
    flags: list[FlagOut] = []
    flags_header: str | None = None
