from __future__ import annotations

from pydantic import BaseModel, Field

from arp.extraction.extractor_agent import ExtractionDraft, format_evidence
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import DocumentChunk
from arp.schemas.datapoints import FieldDefinition

_SYSTEM_PROMPT = """\
You are an independent verification analyst. Another analyst extracted a \
data point from company disclosures; your job is to catch their mistakes, \
not to rubber-stamp them.

Re-read the same evidence and check: does the cited quote actually say \
what the extracted value claims? Is the unit/scale right (e.g. millions \
vs. thousands, % vs. absolute)? Is it the fiscal period the instructions \
call for? Does the value follow the extraction instructions exactly, \
including correctly reporting "not found" when nothing is disclosed?

Set agrees=false and provide corrected_value whenever you find a problem, \
even a small one. confidence should reflect your own certainty after this \
check, not the original analyst's stated confidence. Be skeptical."""


class VerifierOutput(BaseModel):
    agrees: bool
    corrected_value: str | float | bool | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str


async def verify_extraction(
    company_name: str,
    field: FieldDefinition,
    chunks: list[DocumentChunk],
    draft: ExtractionDraft,
    llm: LLMClient,
) -> tuple[VerifierOutput, LLMUsage]:
    prompt = (
        f"Company: {company_name}\n\n"
        f"Field: {field.name}\n"
        f"Description: {field.description}\n"
        f"Extraction instructions: {field.extraction_instructions}\n\n"
        f"Evidence:\n{format_evidence(chunks)}\n\n"
        f"Extracted value to verify: {draft.value!r}\n"
        f"Raw text cited: {draft.raw_value_text!r}\n"
        f"Extractor's citations: {[c.model_dump() for c in draft.citations]}\n"
        f"Extractor's stated confidence: {draft.confidence}"
    )
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=VerifierOutput)
