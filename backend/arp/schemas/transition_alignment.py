from __future__ import annotations

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
