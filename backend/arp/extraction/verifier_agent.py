from __future__ import annotations

import math
from enum import StrEnum

from pydantic import BaseModel, Field

from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue, extract_field, format_evidence
from arp.llm.base import LLMClient, LLMUsage
from arp.normalise.value import TypedValue, typed_value
from arp.orchestration.review_queue import same_value
from arp.schemas.common import Citation, DocumentChunk
from arp.schemas.datapoints import FieldDefinition, ValueState

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
corrected value for the first value listed (values[0]). Set disagreement_type \
to what is wrong with values[0]: value, unit_or_scale, period, entity (another \
company or segment), or not_disclosed; none when you agree. Back a correction \
with citations whose quote is an EXACT, VERBATIM substring of the evidence, \
tagged with its doc_id and passage_id: a correction without one is not applied. \
confidence should reflect your own certainty after this check, not the original \
analyst's stated confidence. Be skeptical."""


class DisagreementType(StrEnum):
    NONE = "none"
    VALUE = "value"
    UNIT_OR_SCALE = "unit_or_scale"
    PERIOD = "period"
    ENTITY = "entity"
    NOT_DISCLOSED = "not_disclosed"


class VerifierOutput(BaseModel):
    agrees: bool
    corrected_value: str | float | bool | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str
    disagreement_type: DisagreementType = DisagreementType.NONE
    citations: list[Citation] = Field(default_factory=list)


def format_values(draft: ExtractionDraft) -> str:
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
        f"Extracted values to verify (values[0] first):\n{format_values(draft)}\n"
        f"Extractor's stated confidence: {draft.confidence}"
    )
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=VerifierOutput)


def _power_of_ten_apart(a, b) -> bool:
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and x for x in (a, b)):
        return False
    exp = round(math.log10(abs(a / b)))
    return exp != 0 and math.isclose(abs(a / b), 10.0**exp, rel_tol=1e-6)


def compare(
    draft: ExtractionDraft, blind: ExtractionDraft, field: FieldDefinition, *,
    planned_periods: list[str] | None = None, fiscal_year_end: str | None = None,
) -> tuple[DisagreementType, PeriodValue | None]:
    """How the blind re-extraction differs from the draft's values[0] (the entry
    a correction applies to), and the blind entry it was compared with."""
    planned = set(planned_periods or ())

    def typed(pv: PeriodValue) -> TypedValue:
        return typed_value(field, pv, fiscal_year_end=fiscal_year_end, planned=planned)

    if not draft.values or not blind.values:
        return (DisagreementType.NONE if not draft.values and not blind.values else DisagreementType.NOT_DISCLOSED,
                blind.values[0] if blind.values else None)
    d = typed(draft.values[0])
    blinds = [(pv, typed(pv)) for pv in blind.values]
    match = next(((pv, t) for pv, t in blinds if t.period_end == d.period_end), None) if d.period_end else blinds[0]
    if match is None:
        return DisagreementType.PERIOD, None
    pv, b = match
    if (d.value_state == ValueState.NOT_FOUND) != (b.value_state == ValueState.NOT_FOUND):
        return DisagreementType.NOT_DISCLOSED, pv
    dc, bc = d.canonical_value, b.canonical_value
    if same_value(dc, bc) if dc is not None and bc is not None else same_value(d.value, b.value):
        return DisagreementType.NONE, pv
    if same_value(d.value, b.value) or _power_of_ten_apart(d.value, b.value) or _power_of_ten_apart(dc, bc):
        return DisagreementType.UNIT_OR_SCALE, pv
    return DisagreementType.VALUE, pv


async def blind_verify(
    company_name: str,
    field: FieldDefinition,
    evidence: list[DocumentChunk],
    draft: ExtractionDraft,
    verifier_llm: LLMClient,
    planned_periods: list[str] | None = None,
    fiscal_year_end: str | None = None,
) -> tuple[VerifierOutput, LLMUsage]:
    """E38: the verifier client extracts the field again without seeing the
    draft; the disagreement is decided here in code, not by the model."""
    blind, usage = await extract_field(company_name, field, evidence, verifier_llm, planned_periods)
    kind, pv = compare(draft, blind, field, planned_periods=planned_periods, fiscal_year_end=fiscal_year_end)
    agrees = kind == DisagreementType.NONE
    # A period mismatch has no blind value for the draft's period to offer.
    offer = pv if not agrees and kind != DisagreementType.PERIOD else None
    found = repr(offer.raw_value_text or offer.value) if offer else "no value for the same period"
    return VerifierOutput(
        agrees=agrees,
        corrected_value=offer.value if offer else None,
        confidence=blind.confidence,
        notes="Blind re-extraction agrees." if agrees else f"Blind re-extraction differs ({kind.value}): {found}.",
        disagreement_type=kind,
        citations=offer.citations if offer else [],
    ), usage
