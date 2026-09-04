from __future__ import annotations

from pydantic import BaseModel, Field

from arp.extraction.extractor_agent import format_evidence
from arp.extraction.tnfd_extractor_agent import (
    CoreGlobalMetricDraft,
    DisclosureDraft,
    GeneralRequirementsDraft,
    SectorLeapConsiderationDraft,
    SectorMetricDraft,
    TNFDExtractionDraft,
)
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import DocumentChunk

_SYSTEM_PROMPT = """\
You are an independent verification analyst reviewing another analyst's \
TNFD (nature-related financial disclosure) extraction from the same \
evidence. Your job is to catch their mistakes, not to rubber-stamp them --
review each of the five sections independently, since an error in one \
doesn't imply the others are wrong.

For disclosures: is disclosed=true only when the recommendation is \
genuinely addressed? Does each cited quote actually support the summary? \
Is materiality_basis/disclosure_scope/leap_stage_reference actually \
supported by the evidence, or inferred?

For core global metrics and sector metrics: does the cited quote actually \
support the extracted value/unit/baseline_year? Was any figure inferred/ \
computed rather than directly disclosed (not allowed)? For sector \
metrics, is metric_no correct and is_core_sector_metric accurate?

For sector LEAP considerations and general requirements: is the content \
actually grounded in the evidence, or does it overreach?

For each section, set its *_agree field to false and provide the \
corrected_* value (the full corrected content for that section, not just \
the changed part) whenever you find any problem with it, even a small \
one -- leave corrected_* null only when that section needed no changes. \
confidence should reflect your own overall certainty across all five \
sections after this check, not the original analyst's stated confidence. \
Be skeptical."""


class TNFDVerifierOutput(BaseModel):
    disclosures_agree: bool
    corrected_disclosures: list[DisclosureDraft] | None = None
    disclosures_notes: str = ""
    core_global_metrics_agree: bool
    corrected_core_global_metrics: list[CoreGlobalMetricDraft] | None = None
    core_global_metrics_notes: str = ""
    sector_metrics_agree: bool
    corrected_sector_metrics: list[SectorMetricDraft] | None = None
    sector_metrics_notes: str = ""
    sector_leap_considerations_agree: bool
    corrected_sector_leap_considerations: list[SectorLeapConsiderationDraft] | None = None
    sector_leap_considerations_notes: str = ""
    general_requirements_agree: bool
    corrected_general_requirements: GeneralRequirementsDraft | None = None
    general_requirements_notes: str = ""
    confidence: float = Field(ge=0.0, le=1.0)


async def verify_tnfd(
    company_name: str,
    chunks: list[DocumentChunk],
    draft: TNFDExtractionDraft,
    llm: LLMClient,
) -> tuple[TNFDVerifierOutput, LLMUsage]:
    prompt = (
        f"Company: {company_name}\n\n"
        f"Evidence:\n{format_evidence(chunks)}\n\n"
        f"Extracted disclosures to verify: {[d.model_dump() for d in draft.disclosures]}\n"
        f"Extracted core global metrics to verify: {[m.model_dump() for m in draft.core_global_metrics]}\n"
        f"Extracted sector metrics to verify: {[m.model_dump() for m in draft.sector_metrics]}\n"
        f"Extracted sector LEAP considerations to verify: "
        f"{[c.model_dump() for c in draft.sector_leap_considerations]}\n"
        f"Extracted general requirements to verify: "
        f"{draft.general_requirements.model_dump() if draft.general_requirements else None}\n"
        f"Extractor's stated confidence: {draft.confidence}"
    )
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=TNFDVerifierOutput)
