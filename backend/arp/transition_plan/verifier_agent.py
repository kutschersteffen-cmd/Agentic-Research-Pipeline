from __future__ import annotations

from pydantic import BaseModel, Field

from arp.extraction.extractor_agent import format_evidence
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import DocumentChunk
from arp.schemas.transition_plan import TransitionPlanIndicator, Verdict
from arp.transition_plan.indicator_agent import IndicatorAnswerDraft

_SYSTEM_PROMPT = """\
You are an independent verification analyst, also a climate-science expert. Another analyst assessed a company's \
climate transition disclosures against one indicator; your job is to catch their mistakes, not to rubber-stamp them.

Re-read the same evidence and check: does the cited quote actually support the verdict? Is the answer being \
appropriately skeptical of greenwashing and cheap talk, or did the first analyst take a vague, unverifiable \
statement at face value? Is NA used correctly -- only when the question does not apply to this company at all, \
never as a stand-in for "not disclosed" (which is NO)? Does the answer avoid presupposing something the report \
never states?

Set agrees=false and provide corrected_verdict whenever you find a problem, even a small one -- including a \
verdict that is directionally right but resting on citations that don't actually say what the first analyst \
claims. confidence should reflect your own certainty after this check, not the original analyst's tone. Be \
skeptical."""


class IndicatorVerifierOutput(BaseModel):
    agrees: bool
    corrected_verdict: Verdict | None = Field(
        default=None, description="Required whenever agrees=false; the verdict this analyst would give instead."
    )
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str


async def verify_indicator(
    company_name: str,
    indicator: TransitionPlanIndicator,
    chunks: list[DocumentChunk],
    draft: IndicatorAnswerDraft,
    llm: LLMClient,
) -> tuple[IndicatorVerifierOutput, LLMUsage]:
    prompt = (
        f"Company: {company_name}\n\n"
        f"Question: {indicator.question}\n"
        f"Guideline: {indicator.guideline}\n\n"
        f"Evidence:\n{format_evidence(chunks)}\n\n"
        f"Verdict to verify: {draft.verdict.value}\n"
        f"Analyst's answer: {draft.answer!r}\n"
        f"Analyst's citations: {[c.model_dump() for c in draft.citations]}"
    )
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=IndicatorVerifierOutput)
