from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


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


class BenchmarksOut(BaseModel):
    version: int
    licence_note: str
    sectors: list[SectorBenchmarksOut]  # in file order


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


class TransitionOut(BaseModel):
    in_scope: bool
    reason: str | None
    sector: str | None
    benchmarks_version: int
    rule_book_version: int
    capex: CapexOut | None
    # Phase-2 keys, served empty now (R9).
    regions: list[str] = []
    actions: list[dict] = []
    b02a: dict | None = None
    assumptions: list[dict] = []
