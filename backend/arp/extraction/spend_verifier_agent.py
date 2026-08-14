from __future__ import annotations

from pydantic import BaseModel, Field

from arp.extraction.spend_extractor_agent import AmountMetricDraft, SpendCategoryDraft


class SpendVerifierOutput(BaseModel):
    """CapEx- or R&D-only slice of a combined verifier output -- see
    SpendExtractionDraft for why this stays a standalone model."""

    agrees: bool
    corrected_total: AmountMetricDraft | None = None
    corrected_description: str | None = None
    corrected_categories: list[SpendCategoryDraft] | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str
