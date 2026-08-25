from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from arp.schemas.common import Citation, now_iso


class IndicatorCategory(StrEnum):
    TARGET = "target"
    GOVERNANCE = "governance"
    STRATEGY = "strategy"
    TRACKING = "tracking"


class WalkOrTalk(StrEnum):
    WALK = "walk"
    TALK = "talk"


class Verdict(StrEnum):
    YES = "YES"
    NO = "NO"
    NA = "NA"


class TransitionPlanIndicator(BaseModel):
    """One of the 64 assessment indicators from Colesanti Senni, Schimanski,
    Bingler, Ni & Leippold (2024), 'Using AI to assess corporate climate
    transition disclosures' -- static reference data, not a per-run record.
    See arp/transition_plan/indicators.py for the loader.
    """

    number: int = Field(description="1-64, the paper's sequential indicator number.")
    identifier: str = Field(description="The original masterfile identifier, e.g. 'A_headline_1'.")
    category: IndicatorCategory
    walk_or_talk: WalkOrTalk
    question: str
    guideline: str = Field(description="Expert-centric question extension: guidance on how to interpret and answer the question.")


class IndicatorAssessment(BaseModel):
    """One indicator's verdict for one company, produced by the RAG pipeline
    in arp/transition_plan/indicator_graph.py.
    """

    number: int
    identifier: str
    category: IndicatorCategory
    walk_or_talk: WalkOrTalk
    question: str
    verdict: Verdict
    answer: str = Field(default="", description="The model's explanation, grounded in the cited evidence.")
    citations: list[Citation] = Field(default_factory=list)
    grounded: bool = Field(default=False)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    needs_review: bool = False
    assessment_error: bool = Field(
        default=False,
        description="True when the model never produced a schema-valid answer for this indicator after every "
        "self-correction retry (see LangChainAnthropicClient.complete_structured), so `verdict` here is NA by "
        "default rather than a real determination -- distinct from a genuine paper-defined NA. Always paired "
        "with needs_review=True.",
    )


class CategoryBreakdown(BaseModel):
    category: IndicatorCategory
    disclosed_count: int = 0
    total_count: int = 0


class TransitionPlanAssessmentRecord(BaseModel):
    """One company's full 64-indicator transition plan assessment."""

    company_id: str
    ticker: str | None = None
    name: str
    run_id: str
    company_sector: str | None = None
    company_location: str | None = None
    report_year: str | None = None
    indicators: list[IndicatorAssessment] = Field(default_factory=list)
    disclosed_count: int = Field(default=0, description="Count of YES verdicts out of 64 -- the paper's core disclosure-completeness metric.")
    walk_disclosed_count: int = 0
    walk_total_count: int = 0
    talk_disclosed_count: int = 0
    talk_total_count: int = 0
    by_category: list[CategoryBreakdown] = Field(default_factory=list)
    overall_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    needs_review: bool = False
    generated_at: str = Field(default_factory=now_iso)
