from __future__ import annotations

from pydantic import BaseModel, Field

from arp.schemas.common import Citation, DocType
from arp.schemas.spend import SpendTopic

# CapEx/R&D figures and their qualitative discussion show up more broadly
# than segment reporting notes: 10-Ks, sustainability reports (green capex),
# investor decks, and earnings call commentary.
SPEND_DOC_TYPES = [
    DocType.ANNUAL_REPORT_10K,
    DocType.SUSTAINABILITY_REPORT,
    DocType.INVESTOR_PRESENTATION,
    DocType.EARNINGS_TRANSCRIPT,
]

SPEND_KEYWORDS: dict[SpendTopic, list[str]] = {
    SpendTopic.CAPEX: [
        "capital expenditure",
        "capital expenditures",
        "capex",
        "capital investment",
        "purchases of property and equipment",
        "property, plant and equipment",
        "capitalized software",
        "additions to property, plant and equipment",
        "investing activities",
    ],
    SpendTopic.RND: [
        "research and development",
        "r&d expense",
        "r&d expenditure",
        "research and development costs",
        "product development",
        "engineering and development",
    ],
}

TOPIC_GUIDANCE: dict[SpendTopic, str] = {
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

SPEND_RULES = """\
- Only report a figure that is explicitly disclosed in the evidence. \
  NEVER estimate, infer, back into, or compute a figure that isn't itself \
  stated (e.g. do not derive CapEx from a depreciation schedule).
- If the total isn't disclosed, set total.value to null and leave its \
  citations empty; still report categories/description if those ARE \
  disclosed.
- If the company doesn't break the spend into categories, return an empty \
  categories list rather than inventing a breakdown.
- If the evidence shows materially conflicting figures for the total \
  (e.g. restated numbers across different documents), set \
  conflicting_sources=true and use the most authoritative/recent figure \
  as the primary value, citing both."""


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
    """CapEx- or R&D-only slice of a combined extractor draft -- kept as its
    own model so the spend aggregation logic (grounding, review-flagging)
    can be reused unchanged by wrapping a section of the combined draft in
    this shape. See arp/extraction/financials_aggregator.py."""

    total: AmountMetricDraft = Field(default_factory=AmountMetricDraft)
    description: str | None = None
    description_citations: list[Citation] = Field(default_factory=list)
    currency: str | None = None
    fiscal_period: str | None = None
    categories: list[SpendCategoryDraft] = Field(default_factory=list)
    conflicting_sources: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
