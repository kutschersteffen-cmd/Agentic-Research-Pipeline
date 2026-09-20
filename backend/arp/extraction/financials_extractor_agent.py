from __future__ import annotations

from pydantic import BaseModel, Field

from arp.extraction.extractor_agent import format_evidence
from arp.extraction.segment_extractor_agent import SEGMENT_GUIDANCE, SegmentDraft
from arp.extraction.spend_extractor_agent import (
    SPEND_RULES,
    TOPIC_GUIDANCE,
    AmountMetricDraft,
    SpendCategoryDraft,
)
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import Citation, DocumentChunk
from arp.schemas.spend import SpendTopic

_SYSTEM_PROMPT = f"""\
You are a precise financial reporting analyst extracting three things at \
once from a company's disclosures (annual report/10-K, sustainability \
report, investor presentation, or earnings call transcript): its business \
segments, its capital expenditure (CapEx), and its R&D expense. These \
typically come from different parts of the filing (a segment note vs. the \
cash flow statement vs. the income statement / MD&A) -- read the evidence \
for each independently and do not conflate them.

=== 1. Business segments ===
{SEGMENT_GUIDANCE}

=== 2. CapEx ===
{TOPIC_GUIDANCE[SpendTopic.CAPEX]}
{SPEND_RULES}

=== 3. R&D ===
{TOPIC_GUIDANCE[SpendTopic.RND]}
{SPEND_RULES}

Also, for CapEx and R&D, extract:
- description: a plain-language summary, in your own words but grounded \
  only in what the evidence actually says, of what the spend is going \
  toward -- e.g. what it's funding, stated priorities/focus areas, or \
  strategic rationale the company itself gives. Cite the sentence(s) it's \
  based on. Leave null if the evidence contains only a bare figure with no \
  qualitative discussion.

General rules (apply to all three sections):
- Only report a segment/figure that is explicitly disclosed in the \
  evidence. NEVER estimate, infer, back into, or compute a figure that \
  isn't itself stated.
- Every citation's `quote` must be an EXACT, VERBATIM substring copied \
  from the evidence block, tagged with the matching doc_id.
- currency/fiscal_period at the top level should reflect the company's \
  primary reporting currency and the most recent fiscal period covered by \
  the evidence, used as the default for all three sections unless a \
  section's own evidence clearly states otherwise.
- confidence should reflect your overall certainty across all three \
  sections together."""


class SpendSectionDraft(BaseModel):
    total: AmountMetricDraft = Field(default_factory=AmountMetricDraft)
    description: str | None = None
    description_citations: list[Citation] = Field(default_factory=list)
    categories: list[SpendCategoryDraft] = Field(default_factory=list)
    conflicting_sources: bool = False


class FinancialsExtractionDraft(BaseModel):
    currency: str | None = None
    fiscal_period: str | None = None
    segments: list[SegmentDraft] = Field(default_factory=list)
    capex: SpendSectionDraft = Field(default_factory=SpendSectionDraft)
    rnd: SpendSectionDraft = Field(default_factory=SpendSectionDraft)
    confidence: float = Field(ge=0.0, le=1.0)


async def extract_financials(
    company_name: str, chunks: list[DocumentChunk], llm: LLMClient
) -> tuple[FinancialsExtractionDraft, LLMUsage]:
    prompt = f"Company: {company_name}\n\nEvidence:\n{format_evidence(chunks)}"
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=FinancialsExtractionDraft)
