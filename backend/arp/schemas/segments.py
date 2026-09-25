from __future__ import annotations

from pydantic import BaseModel, Field

from arp.schemas.common import Citation


class SegmentMetric(BaseModel):
    """A single disclosed figure (revenue, income, or assets) for a segment,
    grounded the same way a scalar extraction field is: a value only counts
    as trustworthy once its citations pass the programmatic grounding check.
    """

    value: float | None = Field(default=None, description="Normalized numeric value, e.g. in the disclosed unit/currency.")
    raw_value_text: str | None = Field(default=None, description="Verbatim text the value was parsed from.")
    citations: list[Citation] = Field(default_factory=list)
    grounded: bool = Field(default=False)


class BusinessSegment(BaseModel):
    name: str
    description: str | None = Field(default=None, description="What the segment does/sells, grounded in the evidence.")
    description_citations: list[Citation] = Field(default_factory=list)
    revenue: SegmentMetric = Field(default_factory=SegmentMetric)
    income: SegmentMetric = Field(default_factory=SegmentMetric, description="Segment operating income / profit, as reported by the company.")
    assets: SegmentMetric = Field(default_factory=SegmentMetric)
    currency: str | None = None
    fiscal_period: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    grounded: bool = Field(default=False, description="True only if every citation across name/description/revenue/income/assets grounded.")
    verifier_notes: str | None = None
    conflicting_sources: bool = False