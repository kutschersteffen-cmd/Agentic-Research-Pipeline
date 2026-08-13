from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from arp.schemas.common import Citation, now_iso


class SpendTopic(StrEnum):
    CAPEX = "capex"
    RND = "rnd"


class AmountMetric(BaseModel):
    """A single disclosed figure, grounded the same way a scalar extraction
    field is: a value only counts as trustworthy once its citations pass
    the programmatic grounding check.
    """

    value: float | None = Field(default=None, description="Normalized numeric value, in the disclosed unit/currency.")
    raw_value_text: str | None = Field(default=None, description="Verbatim text the value was parsed from.")
    citations: list[Citation] = Field(default_factory=list)
    grounded: bool = Field(default=False)


class SpendCategory(BaseModel):
    """One itemized sub-category/program within the topic's total spend
    (e.g. a capex category like "capitalized software", or an R&D focus
    area/program), only populated when the company itself discloses a
    breakdown -- never invented to fill out a list.
    """

    name: str
    description: str | None = Field(default=None, description="What this category covers, grounded in the evidence.")
    description_citations: list[Citation] = Field(default_factory=list)
    amount: AmountMetric = Field(default_factory=AmountMetric)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    grounded: bool = Field(default=False)
    conflicting_sources: bool = False


class SpendExtractionRecord(BaseModel):
    company_id: str
    ticker: str | None = None
    name: str
    topic: SpendTopic
    run_id: str
    total: AmountMetric = Field(default_factory=AmountMetric, description="Total disclosed spend for the most recent fiscal year.")
    description: str | None = Field(
        default=None, description="Plain-language summary of what the spend covers/is going toward, grounded in the evidence."
    )
    description_citations: list[Citation] = Field(default_factory=list)
    currency: str | None = None
    fiscal_period: str | None = None
    categories: list[SpendCategory] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    grounded: bool = Field(default=False)
    verifier_notes: str | None = None
    conflicting_sources: bool = False
    overall_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    needs_review: bool = False
    generated_at: str = Field(default_factory=now_iso)
