from __future__ import annotations

from pydantic import BaseModel, Field

from arp.schemas.revenue_exposure import MetricExposure


class RDExposureResult(BaseModel):
    """A company's R&D-spend-intensity + news-mention-based exposure to one
    pre-revenue/emerging-stage taxonomy activity (Method C) -- computed
    only when ActivityDefinition.lifecycle_stage is ideation/innovation,
    since Method B's revenue-percentage scoring (revenue_exposure.py)
    doesn't apply to an activity with no meaningful revenue yet.

    Kept separate from revenue_exposure/indirect_exposure on CompanyMatch
    and deliberately not banded into an ExposureEstimate here -- this
    codebase tracks quantitative signals separately rather than blending
    them into one score (see docs/METHODOLOGY.md).
    """

    activity_id: str
    rd_intensity: MetricExposure = Field(
        description="Extracted R&D-spend intensity signal for this activity, from the company's disclosures."
    )
    news_mentions: MetricExposure = Field(
        description="Web-search-based recent-momentum signal for this company x activity pair."
    )
    sector_relevant: bool = Field(
        description="Whether the company's resolved ISIC code plausibly overlaps this activity's "
        "core_isic_codes -- gates whether rd_intensity extraction was attempted."
    )
