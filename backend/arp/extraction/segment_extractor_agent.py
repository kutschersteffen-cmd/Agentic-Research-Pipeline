from __future__ import annotations

from pydantic import BaseModel, Field

from arp.schemas.common import Citation, DocType

# Segment reporting figures live almost exclusively in the annual filing's
# "Segment Information" note, occasionally restated in an investor deck.
SEGMENT_DOC_TYPES = [DocType.ANNUAL_REPORT_10K, DocType.PROXY_DEF14A, DocType.INVESTOR_PRESENTATION]

SEGMENT_KEYWORDS = [
    "segment",
    "segments",
    "reportable segment",
    "reportable segments",
    "operating segment",
    "operating segments",
    "business segment",
    "segment revenue",
    "segment income",
    "segment profit",
    "segment assets",
    "revenue by segment",
    "segment reporting",
    "reconciliation of segment",
]

SEGMENT_GUIDANCE = """\
Business/reportable segments (typically the "Segment Reporting" / \
"Segment Information" note in the annual report or 10-K, sometimes \
repeated in an investor presentation): for every distinct segment the \
company reports (as the company itself defines them -- do not invent, \
merge, or split segments), extract:
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
Segment-specific rules:
- If a metric isn't disclosed for a segment, set its value to null and \
  leave its citations empty -- do not omit the segment itself for that.
- If the evidence shows materially conflicting figures for the same \
  segment/metric (e.g. restated numbers across different documents), set \
  that segment's conflicting_sources=true and use the most authoritative/ \
  recent figure as the primary value, citing both.
- If the company discloses only a single reportable segment, or segment \
  reporting is not found in the evidence at all, return an empty segments \
  list rather than guessing."""


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
