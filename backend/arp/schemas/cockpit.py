"""API model of the StewardIQ cockpit (spec `stewardship-cockpit`)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class CockpitScope(BaseModel):
    portfolio_id: str | None
    label: str


class CockpitPortfolioOption(BaseModel):
    portfolio_id: str
    name: str


class CockpitSummary(BaseModel):
    selected: int
    engaged_selected: int
    engaged_outside_selection: int


class CockpitDay(BaseModel):
    date: date
    engagement_meetings: int
    shareholder_meetings: int


class CockpitTierCount(BaseModel):
    tier: str
    selected: int
    engaged: int


class CockpitTierTotal(CockpitTierCount):
    label: str


class CockpitThemeRow(BaseModel):
    theme: str
    selected: int
    engaged: int
    tiers: list[CockpitTierCount]


class CockpitEngagementMeeting(BaseModel):
    date: date
    company_id: str
    company: str
    engagement_id: str
    theme: str
    objective: str | None
    step: int
    stage: str


class CockpitShareholderMeeting(BaseModel):
    date: date
    company_id: str
    company: str
    items: int
    flagged: int | None
    ballot_state: str
    action_due: bool
    days_to_meeting: int
    run_id: str | None


class CockpitControlGap(BaseModel):
    company_id: str
    company: str
    engagement_id: str
    theme: str
    open_days: int | None
    gaps: list[str]


class CockpitLadderCompany(BaseModel):
    company_id: str
    company: str


class CockpitLadderStep(BaseModel):
    step: int
    stage: str
    label: str
    companies: list[CockpitLadderCompany]


class CockpitTopicCount(BaseModel):
    topic: str
    votes: int
    against_management: int


class CockpitVoting(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    season: int
    meetings: int
    votes: int
    for_: int = Field(alias="for")
    against: int
    abstain: int
    other: int
    against_management: int
    topics: list[CockpitTopicCount]


class CockpitResponse(BaseModel):
    as_of: date
    scope: CockpitScope
    portfolios: list[CockpitPortfolioOption]
    demo: bool
    summary: CockpitSummary
    days: list[CockpitDay]
    tiers: list[CockpitTierTotal]
    themes: list[CockpitThemeRow]
    engagement_meetings: list[CockpitEngagementMeeting]
    shareholder_meetings: list[CockpitShareholderMeeting]
    control_gaps: list[CockpitControlGap]
    ladder: list[CockpitLadderStep]
    voting: CockpitVoting
    emissions: None = None  # PR 2 of the spec
