from __future__ import annotations

from pydantic import BaseModel, Field

from arp.schemas.common import Citation, ProvenanceInfo, now_iso
from arp.schemas.segments import BusinessSegment
from arp.schemas.spend import AmountMetric, SpendCategory


class SpendSummary(BaseModel):
    """CapEx or R&D within a CompanyFinancialsRecord -- same shape as
    SpendExtractionRecord minus the company/topic identity fields, which
    the parent record already carries once for both sections.
    """

    total: AmountMetric = Field(default_factory=AmountMetric)
    description: str | None = None
    description_citations: list[Citation] = Field(default_factory=list)
    categories: list[SpendCategory] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    grounded: bool = False
    verifier_notes: str | None = None
    conflicting_sources: bool = False


class CompanyFinancialsRecord(BaseModel):
    """Business segments, CapEx, and R&D for one company, extracted in a
    single evidence-gathering + extractor/verifier pass -- these three are
    almost always wanted together, so pulling them separately would mean
    re-fetching the same documents and re-running near-identical LLM calls
    three times per company.
    """

    company_id: str
    ticker: str | None = None
    name: str
    run_id: str
    currency: str | None = None
    fiscal_period: str | None = None
    segments: list[BusinessSegment] = Field(default_factory=list)
    segments_verifier_notes: str | None = None
    capex: SpendSummary = Field(default_factory=SpendSummary)
    rnd: SpendSummary = Field(default_factory=SpendSummary)
    overall_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    needs_review: bool = False
    generated_at: str = Field(default_factory=now_iso)
    provenance: ProvenanceInfo | None = Field(
        default=None, description="Which extractor/verifier model+prompt version produced this record."
    )
