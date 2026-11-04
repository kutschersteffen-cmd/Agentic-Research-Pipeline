from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from arp.schemas.common import Citation


class InferStock(BaseModel):
    """A stock as selected for inference; `weight` is a fraction, None when the input is unweighted."""

    company_id: str
    name: str
    ticker: str | None = None
    weight: float | None = None
    isin: str | None = None
    sedol: str | None = None
    lei: str | None = None
    cik: str | None = None
    codes: dict[str, str] = Field(default_factory=dict)


class Selection(BaseModel):
    method: Literal["weighted", "sample"]
    cutoff_reason: Literal["cap_30", "weight_80", "sample", "all"]
    total_weight: float | None = None


class StockProfile(BaseModel):
    company_id: str
    name: str
    weight: float | None = None
    isin: str | None = None
    sedol: str | None = None
    db_match: str | None = None  # "none" when unmatched
    codes: dict = Field(default_factory=dict)
    exiobase: list[str] = Field(default_factory=list)
    facts: list[dict] = Field(default_factory=list)
    segments: list[dict] = Field(default_factory=list)
    description: str | None = None
    citation: Citation | None = None
    error: str | None = None


class Cluster(BaseModel):
    cluster_id: int
    terms: list[str] = Field(default_factory=list)
    members: list[str] = Field(default_factory=list)
    weight_share: float | None = None


class Theme(BaseModel):
    rank: int
    name: str
    description: str
    supporting: list[str] = Field(default_factory=list)
    count_share: float
    weight_share: float | None = None
    cluster_ids: list[int] = Field(default_factory=list)
    stated_in_methodology: bool = False
    methodology_quote: str | None = None


class InferRun(BaseModel):
    run_id: str
    stage: Literal["started", "profiled", "themes_ready", "drafted", "failed"]
    name: str
    extractor_model: str
    verifier_model: str
    selection: Selection
    profiles: list[StockProfile] = Field(default_factory=list)
    clusters: list[Cluster] = Field(default_factory=list)
    themes: list[Theme] = Field(default_factory=list)
    outliers: list[str] = Field(default_factory=list)
    index_rules: dict | None = None  # typed in PR 2
    taxonomy_id: str | None = None
    activities: list[dict] = Field(default_factory=list)
    mapping: list[dict] = Field(default_factory=list)
    coverage: dict | None = None
