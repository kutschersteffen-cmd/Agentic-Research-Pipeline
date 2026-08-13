from __future__ import annotations

from pydantic import BaseModel, Field

from arp.extraction.extractor_agent import format_evidence
from arp.extraction.spend_extractor_agent import AmountMetricDraft, SpendCategoryDraft, SpendExtractionDraft
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import DocumentChunk
from arp.schemas.spend import SpendTopic


def _system_prompt(topic: SpendTopic) -> str:
    return f"""\
You are an independent verification analyst reviewing another analyst's \
extraction of a company's disclosed {topic.value}. Your job is to catch \
their mistakes, not to rubber-stamp them.

Re-read the same evidence and check: does the cited quote actually say \
what the extracted total claims? Is the unit/scale right (millions vs. \
thousands)? Is it the fiscal period requested, and the most recent one \
available? Was any figure inferred/computed rather than directly \
disclosed (not allowed)? Is the description actually grounded in the \
evidence, or does it overreach beyond what's stated? Is the category \
breakdown, if any, complete and not inventing categories?

Set agrees=false and provide the corrected fields (corrected_total, \
corrected_description, corrected_categories -- the full corrected \
category list, not just the changed ones) whenever you find any problem, \
even a small one. Leave a corrected_* field null/empty only if that part \
was already correct. confidence should reflect your own certainty after \
this check, not the original analyst's stated confidence. Be skeptical."""


class SpendVerifierOutput(BaseModel):
    agrees: bool
    corrected_total: AmountMetricDraft | None = None
    corrected_description: str | None = None
    corrected_categories: list[SpendCategoryDraft] | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str


async def verify_spend(
    topic: SpendTopic,
    company_name: str,
    chunks: list[DocumentChunk],
    draft: SpendExtractionDraft,
    llm: LLMClient,
) -> tuple[SpendVerifierOutput, LLMUsage]:
    prompt = (
        f"Company: {company_name}\n\n"
        f"Evidence:\n{format_evidence(chunks)}\n\n"
        f"Extracted total to verify: {draft.total.model_dump()}\n"
        f"Extracted description: {draft.description!r}\n"
        f"Extracted categories: {[c.model_dump() for c in draft.categories]}\n"
        f"Extractor's stated confidence: {draft.confidence}"
    )
    return await llm.complete_structured(system=_system_prompt(topic), prompt=prompt, output_model=SpendVerifierOutput)
