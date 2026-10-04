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

The extractor reports one value per period. Set agrees=false whenever you \
find a problem with any of them, even a small one; corrected_value is the \
corrected value for the first value listed (values[0]). confidence should \
reflect your own certainty after this check, not the original analyst's stated confidence. Be skeptical."""


class VerifierOutput(BaseModel):
    agrees: bool
    corrected_value: str | float | bool | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str


def _format_values(draft: ExtractionDraft) -> str:
    if not draft.values:
        return "(none: the extractor reports the data point as not disclosed)"
    return "\n".join(
        f"values[{i}]: value={pv.value!r} state={pv.state.value} raw_value_text={pv.raw_value_text!r} "
        f"unit_text={pv.unit_text!r} period_text={pv.period_text!r} basis_text={pv.basis_text!r} "
        f"citations={[c.model_dump(include={'doc_id', 'passage_id', 'quote'}) for c in pv.citations]}"
        for i, pv in enumerate(draft.values)
    )


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
        f"Extracted values to verify (values[0] first):\n{_format_values(draft)}\n"
        f"Extractor's stated confidence: {draft.confidence}"
    )
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=VerifierOutput)
