from __future__ import annotations

from pydantic import BaseModel, Field

from arp.extraction.extractor_agent import format_evidence
from arp.extraction.financials_extractor_agent import FinancialsExtractionDraft, SpendSectionDraft
from arp.extraction.segment_extractor_agent import SegmentDraft
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import DocumentChunk

_SYSTEM_PROMPT = """\
You are an independent verification analyst reviewing another analyst's \
extraction of a company's business segments, CapEx, and R&D from the same \
evidence. Your job is to catch their mistakes, not to rubber-stamp them --
review each of the three sections independently, since an error in one \
doesn't imply the others are wrong.

For business segments: is the segment list complete (no disclosed segment \
missing, no invented segment)? Does each cited quote actually say what the \
extracted figure claims? Is the unit/scale and fiscal period right?

For CapEx and R&D: does the cited quote actually support the extracted \
total? Is the unit/scale and fiscal period right, and is it the most \
recent period available? Was any figure inferred/computed rather than \
directly disclosed (not allowed)? Is the description actually grounded in \
the evidence, or does it overreach? Is the category breakdown, if any, \
complete and not inventing categories?

For each section, set its *_agree field to false and provide the \
corrected_* value (the full corrected content for that section, not just \
the changed part) whenever you find any problem with it, even a small \
one -- leave corrected_* null only when that section needed no changes. \
confidence should reflect your own overall certainty across all three \
sections after this check, not the original analyst's stated confidence. \
Be skeptical."""


class FinancialsVerifierOutput(BaseModel):
    segments_agree: bool
    corrected_segments: list[SegmentDraft] | None = None
    segments_notes: str = ""
    capex_agree: bool
    corrected_capex: SpendSectionDraft | None = None
    capex_notes: str = ""
    rnd_agree: bool
    corrected_rnd: SpendSectionDraft | None = None
    rnd_notes: str = ""
    confidence: float = Field(ge=0.0, le=1.0)


async def verify_financials(
    company_name: str,
    chunks: list[DocumentChunk],
    draft: FinancialsExtractionDraft,
    llm: LLMClient,
) -> tuple[FinancialsVerifierOutput, LLMUsage]:
    prompt = (
        f"Company: {company_name}\n\n"
        f"Evidence:\n{format_evidence(chunks)}\n\n"
        f"Extracted segments to verify: {[s.model_dump() for s in draft.segments]}\n"
        f"Extracted CapEx to verify: {draft.capex.model_dump()}\n"
        f"Extracted R&D to verify: {draft.rnd.model_dump()}\n"
        f"Extractor's stated confidence: {draft.confidence}"
    )
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=FinancialsVerifierOutput)
