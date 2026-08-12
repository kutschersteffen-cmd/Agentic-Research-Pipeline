from __future__ import annotations

from pydantic import BaseModel, Field

from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import Citation, DocumentChunk
from arp.schemas.datapoints import FieldDefinition

_SYSTEM_PROMPT = """\
You are a precise financial/ESG data extraction analyst. You will be given \
a field definition (what to extract, its data type/unit, and explicit \
extraction instructions) and excerpts from a company's disclosures.

Extract the value strictly according to the instructions. Rules:
- If the data point is not disclosed in the evidence, set value to null, \
  confidence to 0, and leave citations empty. NEVER estimate, infer, or \
  compute a value that is not explicitly stated.
- If multiple figures are present (e.g. different fiscal years), follow \
  the extraction_instructions' tie-break rule; if instructions are silent, \
  prefer the most recent fiscal period and note the others in \
  raw_value_text.
- raw_value_text must be the literal text the value was read from.
- Every citation's `quote` must be an EXACT, VERBATIM substring copied \
  from the evidence block, tagged with the matching doc_id.
- If the evidence contains materially conflicting values for this field \
  from different documents, set conflicting_sources=true and pick the most \
  authoritative/recent one as the primary value, citing both."""


def format_evidence(chunks: list[DocumentChunk]) -> str:
    blocks = []
    for c in chunks:
        header = f"[doc_id={c.doc_id} | doc_type={c.doc_type.value}"
        if c.section:
            header += f" | section={c.section}"
        header += "]"
        blocks.append(f"{header}\n{c.text}")
    return "\n\n---\n\n".join(blocks)


class ExtractionDraft(BaseModel):
    value: str | float | bool | None
    raw_value_text: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    conflicting_sources: bool = False


async def extract_field(
    company_name: str, field: FieldDefinition, chunks: list[DocumentChunk], llm: LLMClient
) -> tuple[ExtractionDraft, LLMUsage]:
    prompt = (
        f"Company: {company_name}\n\n"
        f"Field: {field.name}\n"
        f"Description: {field.description}\n"
        f"Data type: {field.data_type.value}"
        + (f" ({field.unit})" if field.unit else "")
        + (f"\nAllowed values: {field.allowed_values}" if field.allowed_values else "")
        + f"\nExtraction instructions: {field.extraction_instructions}\n\n"
        f"Evidence:\n{format_evidence(chunks)}"
    )
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=ExtractionDraft)
