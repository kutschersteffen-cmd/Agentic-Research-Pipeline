from __future__ import annotations

from pydantic import BaseModel, Field

from arp.extraction.extractor_agent import format_evidence
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import Citation, DocumentChunk

_SYSTEM_PROMPT = """\
You are a precise financial reporting analyst extracting a company's \
disclosed business/reportable segments from its filings (typically the \
"Segment Reporting" / "Segment Information" note in the annual report or \
10-K, sometimes repeated in an investor presentation).

For every distinct segment the company reports (as the company itself \
defines them -- do not invent, merge, or split segments), extract:
- name: the segment's name exactly as disclosed.
- description: a plain-language summary, in your own words, of what the \
  segment does/sells, grounded only in what the evidence actually says -- \
  never invented. Cite the sentence(s) it's based on.
- revenue: the segment's reported revenue for the most recent fiscal \
  period, with the exact figure, unit/scale, and a verbatim citation.
- income: the segment's reported operating income / segment profit (use \
  whatever profit measure the company itself reports at the segment \
  level; note which one in raw_value_text if more than one is disclosed).
- assets: the segment's reported total assets, if disclosed (many \
  companies do not disclose assets at the segment level -- leave null, do \
  not estimate).
- currency: the reporting currency (e.g. "USD", "EUR").
- fiscal_period: the fiscal period the figures cover (e.g. "FY2025").

Rules:
- Only report a segment/figure that is explicitly disclosed in the \
  evidence. NEVER estimate, infer, back into, or compute a figure that \
  isn't itself stated (e.g. do not subtract segments from a company total \
  to infer a missing segment's figure).
- If a metric isn't disclosed for a segment, set its value to null and \
  leave its citations empty -- do not omit the segment itself for that.
- Every citation's `quote` must be an EXACT, VERBATIM substring copied \
  from the evidence block, tagged with the matching doc_id.
- If the evidence shows materially conflicting figures for the same \
  segment/metric (e.g. restated numbers across different documents), set \
  that segment's conflicting_sources=true and use the most authoritative/ \
  recent figure as the primary value, citing both.
- If the company discloses only a single reportable segment, or segment \
  reporting is not found in the evidence at all, return an empty segments \
  list rather than guessing.
- confidence should reflect your overall certainty across all segments \
  found."""


class SegmentMetricDraft(BaseModel):
    value: float | None = None
    raw_value_text: str | None = None
    citations: list[Citation] = Field(default_factory=list)


class SegmentDraft(BaseModel):
    name: str
    description: str | None = None
    description_citations: list[Citation] = Field(default_factory=list)
    revenue: SegmentMetricDraft = Field(default_factory=SegmentMetricDraft)
    income: SegmentMetricDraft = Field(default_factory=SegmentMetricDraft)
    assets: SegmentMetricDraft = Field(default_factory=SegmentMetricDraft)
    currency: str | None = None
    fiscal_period: str | None = None
    conflicting_sources: bool = False


class SegmentExtractionDraft(BaseModel):
    segments: list[SegmentDraft] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


async def extract_segments(
    company_name: str, chunks: list[DocumentChunk], llm: LLMClient
) -> tuple[SegmentExtractionDraft, LLMUsage]:
    prompt = f"Company: {company_name}\n\nEvidence:\n{format_evidence(chunks)}"
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=SegmentExtractionDraft)
