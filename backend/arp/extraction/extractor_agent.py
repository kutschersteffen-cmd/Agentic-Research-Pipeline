from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import Citation, DocumentChunk
from arp.schemas.datapoints import FieldDefinition, ValueState

_SYSTEM_PROMPT = """\
You are a precise financial/ESG data extraction analyst. You will be given \
a field definition (what to extract, its data type/unit, and explicit \
extraction instructions) and excerpts from a company's disclosures.

Extract the value strictly according to the instructions. Rules:
- Return one entry in `values` per reported period (e.g. each fiscal \
  year shown), each with its own citations. List the most recent period \
  first.
- An empty `values` list means the data point is not disclosed. NEVER \
  estimate, infer, or compute a value that is not explicitly stated.
- Copy unit_text, period_text and basis_text verbatim from the evidence, \
  including a scale word from a table header (e.g. "in thousands").
- Never convert units or scales yourself: value is the number as printed.
- Use state="zero" only when the document states the value is zero, and \
  state="not_applicable" only when it states the item does not apply.
- raw_value_text must be the literal text each value was read from.
- Every citation's `quote` must be an EXACT, VERBATIM substring copied \
  from the evidence block, tagged with the matching doc_id and the \
passage_id of the block the quote was copied from.
- If the evidence contains materially conflicting values for this field \
  from different documents, set conflicting_sources=true and pick the most \
  authoritative/recent one as the primary value, citing both."""


def format_evidence(chunks: list[DocumentChunk]) -> str:
    blocks = []
    for c in chunks:
        header = f"[doc_id={c.doc_id} | passage_id={c.chunk_id} | doc_type={c.doc_type.value}"
        if c.section:
            header += f" | section={c.section}"
        header += "]"
        blocks.append(f"{header}\n{c.text}")
    return "\n\n---\n\n".join(blocks)


class PeriodValue(BaseModel):
    value: str | float | bool | None = None
    state: ValueState = ValueState.FOUND
    raw_value_text: str | None = None
    unit_text: str | None = None
    period_text: str | None = None
    basis_text: str | None = None
    citations: list[Citation] = Field(default_factory=list)


class ExtractionDraft(BaseModel):
    values: list[PeriodValue] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    conflicting_sources: bool = False

    @model_validator(mode="before")
    @classmethod
    def _from_single_value(cls, data):
        # The old single-value shape: {"value", "raw_value_text", "citations"}.
        if isinstance(data, dict) and "values" not in data and {"value", "raw_value_text", "citations"} & data.keys():
            data = dict(data)
            pv = {k: data.pop(k, None) for k in ("value", "raw_value_text")}
            citations = data.pop("citations", None) or []
            data["values"] = [] if pv["value"] is None and not citations else [{**pv, "citations": citations}]
        return data


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
