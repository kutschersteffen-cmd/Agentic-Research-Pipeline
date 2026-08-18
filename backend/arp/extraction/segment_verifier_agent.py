from __future__ import annotations

from pydantic import BaseModel, Field

from arp.extraction.segment_extractor_agent import SegmentDraft


class SegmentVerifierOutput(BaseModel):
    """Segment-only slice of a combined verifier output -- see
    SegmentExtractionDraft for why this stays a standalone model."""

    agrees: bool
    corrected_segments: list[SegmentDraft] | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str
