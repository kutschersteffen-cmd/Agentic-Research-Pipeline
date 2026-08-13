from __future__ import annotations

from pydantic import BaseModel, Field

from arp.extraction.extractor_agent import format_evidence
from arp.extraction.segment_extractor_agent import SegmentDraft, SegmentExtractionDraft
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import DocumentChunk

_SYSTEM_PROMPT = """\
You are an independent verification analyst reviewing another analyst's \
extraction of a company's disclosed business segments. Your job is to \
catch their mistakes, not to rubber-stamp them.

Re-read the same evidence and check: is the segment list complete (no \
disclosed segment missing, no invented segment)? Does each cited quote \
actually say what the extracted figure claims? Is the unit/scale right \
(millions vs. thousands)? Is it the fiscal period requested? Was any \
figure inferred or computed rather than directly disclosed (not allowed)?

Set agrees=false and provide corrected_segments (the full, corrected \
segment list -- not just the changed segments) whenever you find any \
problem, even a small one. confidence should reflect your own certainty \
after this check, not the original analyst's stated confidence. Be \
skeptical."""


class SegmentVerifierOutput(BaseModel):
    agrees: bool
    corrected_segments: list[SegmentDraft] | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str


async def verify_segments(
    company_name: str,
    chunks: list[DocumentChunk],
    draft: SegmentExtractionDraft,
    llm: LLMClient,
) -> tuple[SegmentVerifierOutput, LLMUsage]:
    prompt = (
        f"Company: {company_name}\n\n"
        f"Evidence:\n{format_evidence(chunks)}\n\n"
        f"Extracted segments to verify: {[s.model_dump() for s in draft.segments]}\n"
        f"Extractor's stated confidence: {draft.confidence}"
    )
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=SegmentVerifierOutput)
