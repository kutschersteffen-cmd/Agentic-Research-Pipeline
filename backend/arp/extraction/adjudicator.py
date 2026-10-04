from __future__ import annotations

from pydantic import BaseModel, Field

from arp.extraction.extractor_agent import ExtractionDraft, format_evidence
from arp.extraction.verifier_agent import DisagreementType, VerifierOutput, format_values
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import Citation, DocumentChunk
from arp.schemas.datapoints import FieldDefinition

_SYSTEM_PROMPT = """\
You are the adjudicating analyst. An extractor and an independent verifier \
read the same company disclosures and disagree about one data point. Decide \
from the evidence alone which reading is right, or give the right value if \
neither is.

Settle only values[0], the value the disagreement is about. Set settled=true \
only when the evidence decides it; then value is the settled value in the \
field's unit (null when the evidence shows it is not disclosed), raw_value_text \
the figure as printed, unit_text its unit and scale as stated (e.g. "USD \
million"), and citations back it with quotes that \
are EXACT, VERBATIM substrings of the evidence, tagged with their doc_id and \
passage_id. A settled value without such a citation is not applied. When the \
evidence does not decide it, set settled=false and explain why in notes. Do not \
split the difference or guess."""


class AdjudicatorOutput(BaseModel):
    settled: bool
    value: str | float | bool | None = None
    raw_value_text: str | None = None
    unit_text: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    notes: str


def disagreement(verifier: VerifierOutput) -> DisagreementType:
    """The verifier's disagreement type, consistent with its `agrees` flag:
    agreement is never a disagreement, and an untyped disagreement is about the value."""
    if verifier.agrees:
        return DisagreementType.NONE
    return verifier.disagreement_type if verifier.disagreement_type != DisagreementType.NONE else DisagreementType.VALUE


async def adjudicate(
    company_name: str,
    field: FieldDefinition,
    chunks: list[DocumentChunk],
    draft: ExtractionDraft,
    verifier: VerifierOutput,
    llm: LLMClient,
) -> tuple[AdjudicatorOutput, LLMUsage]:
    cited = [c.model_dump(include={"doc_id", "passage_id", "quote"}) for c in verifier.citations]
    prompt = (
        f"Company: {company_name}\n\n"
        f"Field: {field.name}\n"
        f"Data type: {field.data_type.value}\n"
        f"Unit: {field.unit or '(none)'}\n"
        f"Description: {field.description}\n"
        f"Extraction instructions: {field.extraction_instructions}\n\n"
        f"Evidence:\n{format_evidence(chunks)}\n\n"
        f"Extractor's values (values[0] first):\n{format_values(draft)}\n\n"
        f"Verifier's position on values[0]:\n"
        f"disagreement_type: {disagreement(verifier).value}\n"
        f"corrected_value: {verifier.corrected_value!r}\n"
        f"citations: {cited}\n"
        f"notes: {verifier.notes}"
    )
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=AdjudicatorOutput)
