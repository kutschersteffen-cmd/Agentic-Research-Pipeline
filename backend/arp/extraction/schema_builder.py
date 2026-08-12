from __future__ import annotations

from pydantic import BaseModel, Field

from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import DocType
from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition

_SYSTEM_PROMPT = """\
You design precise, machine-checkable extraction schemas for pulling data \
points out of company disclosures (10-Ks, sustainability reports, earnings \
call transcripts) at scale.

Given a short natural-language research request (e.g. "green capex", \
"forward-looking business outlook"), propose one or more fields that \
together capture what was asked. For each field:
- Write extraction_instructions precise enough that two different analysts \
  reading the same document would extract the same value: state exactly \
  what counts, common synonyms/phrasing to look for, how to handle a range \
  or multiple figures (e.g. take the most recently reported fiscal year), \
  and what to do when the figure is not disclosed (report as not found, \
  never estimate or infer).
- Pick the correct data_type and, for numeric fields, a unit.
- Suggest 3-8 seed_keywords (including likely synonyms) that would appear \
  near this data point in text, to drive keyword-based evidence retrieval.
- Suggest which document types are most likely to contain it."""


class _FieldDraft(BaseModel):
    name: str
    description: str
    data_type: FieldDataType
    unit: str | None = None
    extraction_instructions: str
    allowed_values: list[str] | None = None
    seed_keywords: list[str] = Field(default_factory=list)
    source_doc_types: list[DocType] = Field(default_factory=list)


class _SchemaDraft(BaseModel):
    name: str
    description: str
    fields: list[_FieldDraft]


async def draft_schema(criteria_text: str, llm: LLMClient) -> tuple[DataPointSchema, LLMUsage]:
    """Turns a natural-language research request into a formal, editable
    DataPointSchema. The user reviews/edits the draft in the UI before any
    extraction run uses it -- this never runs unsupervised against real data.
    """
    prompt = f"Research request: {criteria_text}\n\nPropose the extraction schema per your instructions."
    draft, usage = await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=_SchemaDraft)
    fields = [
        FieldDefinition(
            name=f.name,
            description=f.description,
            data_type=f.data_type,
            unit=f.unit,
            extraction_instructions=f.extraction_instructions,
            allowed_values=f.allowed_values,
            seed_keywords=f.seed_keywords,
            source_doc_types=f.source_doc_types,
        )
        for f in draft.fields
    ]
    return DataPointSchema(name=draft.name, description=draft.description, fields=fields), usage
