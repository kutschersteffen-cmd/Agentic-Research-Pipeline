from __future__ import annotations

import functools
from typing import Literal

from pydantic import BaseModel, Field, StrictBool, create_model, field_validator, model_validator

from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import Citation, DocumentChunk
from arp.schemas.datapoints import FieldDataType, FieldDefinition, ValueState

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
- Never convert units or scales yourself: value is the number as printed   ("$2.0 billion" -> value 2.0, unit_text "$ billion"), even when the   field's extraction instructions ask for a conversion. The app converts.
- Use state="zero" only when the document states the value is zero, and \
  state="not_applicable" only when it states the item does not apply.
- raw_value_text must be the literal text each value was read from.
- Every citation's `quote` must be an EXACT, VERBATIM substring copied \
  from the evidence block, tagged with the matching doc_id and the \
passage_id of the block the quote was copied from.
- If the evidence contains materially conflicting values for this field \
  from different documents, set conflicting_sources=true and pick the most \
  authoritative/recent one as the primary value, citing both."""

BOOLEAN_RULE = (
    "This is a yes/no criterion. value=true: the evidence shows the criterion is met (quote it). "
    "value=false: the evidence addresses this topic but shows the criterion is NOT met (quote what it says instead, "
    "e.g. only an intensity target where an absolute target is asked for). If nothing in the evidence addresses "
    "the topic, return an empty `values` list (not disclosed): never return false for missing evidence. "
    "Where the extraction instructions say 'NO otherwise', apply NO only when the topic is addressed."
    " Where the extraction instructions say to answer N/A, return an empty `values` list (not disclosed); "
    "never use state not_applicable for a yes/no criterion."
)


def format_evidence(chunks: list[DocumentChunk], header: tuple[str, ...] = ("doc_id", "passage_id", "doc_type", "section", "unit_note")) -> str:
    """Chunks as prompt evidence, each under a `[name=value | ...]` line of
    the `header` fields asked for, in that order; section, speaker and unit_note only when set."""
    blocks = []
    for c in chunks:
        values = {"doc_id": c.doc_id, "passage_id": c.chunk_id, "doc_type": c.doc_type.value, "section": c.section, "speaker": c.speaker, "unit_note": c.unit_note}
        fields = " | ".join(f"{name}={values[name]}" for name in header if name not in ("section", "speaker", "unit_note") or values[name])
        blocks.append(f"[{fields}]\n{c.text}")
    return "\n\n---\n\n".join(blocks)


class PeriodValue(BaseModel):
    value: str | float | bool | None = None
    state: ValueState = ValueState.FOUND
    raw_value_text: str | None = None
    unit_text: str | None = None
    period_text: str | None = None
    planned_period_end: str | None = Field(
        default=None, description="The planned period (ISO date from the list given) this value belongs to, if any."
    )
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


def _field_spec(field: FieldDefinition) -> str:
    return (
        f"Field: {field.name}\n"
        f"Description: {field.description}\n"
        f"Data type: {field.data_type.value}"
        + (f" ({field.unit})" if field.unit else "")
        + (f"\nAllowed values: {field.allowed_values}" if field.allowed_values else "")
        + f"\nExtraction instructions: {field.extraction_instructions}\n\n"
        + (f"{BOOLEAN_RULE}\n\n" if field.data_type == FieldDataType.BOOLEAN else "")
    )


def _periods(planned_periods: list[str] | None) -> str:
    if not planned_periods:
        return ""
    return (
        "Report a value for each of these periods where disclosed (period end): "
        f"{', '.join(planned_periods)}. Set planned_period_end to the one each value belongs to; "
        "leave it empty if none fits.\n\n"
    )


def _text(v):
    # a number given for a text field is kept as its text ("11115"), so the format check can flag it
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f"{v:g}" if isinstance(v, float) else str(v)
    return v


@functools.lru_cache(maxsize=256)
def _typed_draft(data_type: FieldDataType, allowed: tuple[str, ...]) -> type[ExtractionDraft]:
    validators = {}
    if data_type == FieldDataType.BOOLEAN:
        vtype = StrictBool | None  # "YES", "true" or 1 are retried, not read as yes
    elif data_type in (FieldDataType.NUMBER, FieldDataType.CURRENCY_AMOUNT, FieldDataType.PERCENTAGE):
        vtype = float | None
    elif data_type == FieldDataType.ENUM and allowed:
        vtype = Literal[allowed] | None
    else:
        vtype = str | None
        validators["_as_text"] = field_validator("value", mode="before")(lambda cls, v: _text(v))
    value = create_model("PeriodValue", __base__=PeriodValue, __validators__=validators, value=(vtype, None))
    return create_model("ExtractionDraft", __base__=ExtractionDraft, values=(list[value], Field(default_factory=list)))


def draft_model_for(field: FieldDefinition) -> type[ExtractionDraft]:
    """The draft format for one field: `value` accepts only the field's type, so a wrong type is retried."""
    return _typed_draft(field.data_type, tuple(field.allowed_values or ()))


async def extract_field(
    company_name: str,
    field: FieldDefinition,
    chunks: list[DocumentChunk],
    llm: LLMClient,
    planned_periods: list[str] | None = None,
) -> tuple[ExtractionDraft, LLMUsage]:
    prompt = f"Company: {company_name}\n\n{_field_spec(field)}{_periods(planned_periods)}Evidence:\n{format_evidence(chunks)}"
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=draft_model_for(field))


_GROUP_RULE = """
- You are given several fields at once. Return one entry in `fields` per field, with its exact field_id and \
its own draft; read each field on its own definition and instructions, never letting one field's value \
stand in for another's."""


class FieldDraft(BaseModel):
    field_id: str
    draft: ExtractionDraft


class GroupDraft(BaseModel):
    fields: list[FieldDraft] = Field(default_factory=list)


async def extract_group(
    company_name: str,
    fields: list[FieldDefinition],
    chunks: list[DocumentChunk],
    llm: LLMClient,
    planned_periods: list[str] | None = None,
) -> tuple[dict[str, ExtractionDraft], LLMUsage]:
    """One call for several fields over their shared evidence: each field's draft by field_id. A field the
    model left out (or an unknown field_id) is simply missing; the caller extracts it on its own."""
    specs = "".join(f"### field_id: {f.field_id}\n{_field_spec(f)}" for f in fields)
    prompt = f"Company: {company_name}\n\n{specs}{_periods(planned_periods)}Evidence:\n{format_evidence(chunks)}"
    out, usage = await llm.complete_structured(system=_SYSTEM_PROMPT + _GROUP_RULE, prompt=prompt, output_model=GroupDraft)
    known = {f.field_id for f in fields}
    return {d.field_id: d.draft for d in out.fields if d.field_id in known}, usage
