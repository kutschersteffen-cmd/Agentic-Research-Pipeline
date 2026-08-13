from __future__ import annotations

from pydantic import BaseModel, Field

from arp.extraction.extractor_agent import format_evidence
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import Citation, DocumentChunk
from arp.schemas.spend import SpendTopic

_TOPIC_GUIDANCE: dict[SpendTopic, str] = {
    SpendTopic.CAPEX: (
        "Total capital expenditure (CapEx): the company's total capital spend for the most recent fiscal year "
        "-- typically 'purchases of property, plant and equipment' / 'additions to PP&E' / capitalized software "
        "from the cash flow statement's investing activities, or a total CapEx figure the company itself states. "
        "If the company separately breaks CapEx into categories (e.g. maintenance vs. growth capex, green/"
        "sustainable capex, capitalized software, real estate, by segment or geography), extract each as a "
        "category with its own name, description, and figure."
    ),
    SpendTopic.RND: (
        "Total research & development (R&D) expense: the company's total R&D spend for the most recent fiscal "
        "year, typically a line item on the income statement ('research and development expenses') or stated "
        "directly. If the company breaks R&D spend into programs/focus areas (e.g. platform engineering, AI "
        "research, new product development) with their own figures, extract each as a category with its own "
        "name, description, and figure."
    ),
}


def _system_prompt(topic: SpendTopic) -> str:
    return f"""\
You are a precise financial reporting analyst extracting a company's \
disclosed {topic.value} from its filings (annual report/10-K, \
sustainability report, investor presentation, or earnings call \
transcript).

What to extract:
{_TOPIC_GUIDANCE[topic]}

Also extract:
- description: a plain-language summary, in your own words but grounded \
  only in what the evidence actually says, of what the spend is going \
  toward -- e.g. what it's funding, stated priorities/focus areas, or \
  strategic rationale the company itself gives. Cite the sentence(s) it's \
  based on. Leave null if the evidence contains only a bare figure with no \
  qualitative discussion.
- currency: the reporting currency (e.g. "USD", "EUR").
- fiscal_period: the fiscal period the total figure covers (e.g. "FY2025").

Rules:
- Only report a figure that is explicitly disclosed in the evidence. \
  NEVER estimate, infer, back into, or compute a figure that isn't itself \
  stated (e.g. do not derive CapEx from a depreciation schedule).
- If the total isn't disclosed, set total.value to null and leave its \
  citations empty; still report categories/description if those ARE \
  disclosed.
- If the company doesn't break the spend into categories, return an empty \
  categories list rather than inventing a breakdown.
- Every citation's `quote` must be an EXACT, VERBATIM substring copied \
  from the evidence block, tagged with the matching doc_id.
- If the evidence shows materially conflicting figures for the total \
  (e.g. restated numbers across different documents), set \
  conflicting_sources=true and use the most authoritative/recent figure \
  as the primary value, citing both.
- confidence should reflect your overall certainty in the total figure \
  and description together."""


class AmountMetricDraft(BaseModel):
    value: float | None = None
    raw_value_text: str | None = None
    citations: list[Citation] = Field(default_factory=list)


class SpendCategoryDraft(BaseModel):
    name: str
    description: str | None = None
    description_citations: list[Citation] = Field(default_factory=list)
    amount: AmountMetricDraft = Field(default_factory=AmountMetricDraft)
    conflicting_sources: bool = False


class SpendExtractionDraft(BaseModel):
    total: AmountMetricDraft = Field(default_factory=AmountMetricDraft)
    description: str | None = None
    description_citations: list[Citation] = Field(default_factory=list)
    currency: str | None = None
    fiscal_period: str | None = None
    categories: list[SpendCategoryDraft] = Field(default_factory=list)
    conflicting_sources: bool = False
    confidence: float = Field(ge=0.0, le=1.0)


async def extract_spend(
    topic: SpendTopic, company_name: str, chunks: list[DocumentChunk], llm: LLMClient
) -> tuple[SpendExtractionDraft, LLMUsage]:
    prompt = f"Company: {company_name}\n\nEvidence:\n{format_evidence(chunks)}"
    return await llm.complete_structured(system=_system_prompt(topic), prompt=prompt, output_model=SpendExtractionDraft)
