"""API models of the stewardship priority worklist (spec `stewardship-priority-worklist`)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Observed(BaseModel):
    value: float | str | bool
    simulated: bool


class Grade(Observed):
    label: str


class TriggerCounts(BaseModel):
    high: int
    medium: int
    low: int


class NextMeeting(BaseModel):
    days: int
    estimated: bool
    last_meeting: str


class ScorePart(BaseModel):
    id: str
    weight: int
    normalised: float
    points: float
    empty: bool


class Selection(BaseModel):
    status: Literal["proposed", "confirmed"]
    proposed_by: str
    proposed_at: str
    confirmed_by: str | None
    confirmed_at: str | None
    weights_version: int


class ProgrammeChip(BaseModel):
    programme_id: str
    name: str
    status: Literal["proposed", "confirmed"]


class WorklistRow(BaseModel):
    issuer_id: str
    company: str
    sector: str
    holdings_weight_pct: float | None
    aum_held_eur_m: float | None
    coverage_tier: str
    coverage_tier_confirmed: bool
    triggers: TriggerCounts
    open_engagements: int
    escalated: int
    overdue_commitments: int
    next_meeting: NextMeeting | None
    transition_grade: Grade | None
    esg_score: Observed | None
    controversy: Observed | None
    carbon_intensity: Observed | None
    score: float
    parts: list[ScorePart]
    selection: Selection | None
    programmes: list[ProgrammeChip]


class WorklistScope(BaseModel):
    key: str
    label: str
    kind: str
    companies: int


class WeightsVersion(BaseModel):
    version: int
    activated_by: str | None
    activated_at: str | None


class Worklist(BaseModel):
    as_of: str
    universe_note: str | None
    scope: WorklistScope
    weights: WeightsVersion
    cycle: str
    rows: list[WorklistRow]


class SelectionRow(Selection):
    issuer_id: str
    company: str
    in_scope: bool


class SelectionList(BaseModel):
    cycle: str
    current: bool
    rows: list[SelectionRow]


class SelectionChange(BaseModel):
    cycle: str | None = None  # the current cycle
    add: list[str] = []
    remove: list[str] = []


class SelectionConfirm(BaseModel):
    cycle: str | None = None


class Confirmed(BaseModel):
    confirmed: int


class PriorityPreviewRequest(BaseModel):
    content: dict


class TopRow(BaseModel):
    issuer_id: str
    company: str
    score: float
    rank: int


class RankMove(BaseModel):
    issuer_id: str
    company: str
    rank_active: int
    rank_candidate: int


class ScoreChange(BaseModel):
    issuer_id: str
    company: str
    active: float
    candidate: float
    change: float


class PriorityPreview(BaseModel):
    companies: int
    top_active: list[TopRow]
    top_candidate: list[TopRow]
    entering_top: list[RankMove]
    leaving_top: list[RankMove]
    score_change: list[ScoreChange]


class Programme(BaseModel):
    programme_id: str
    name: str
    built_in: bool
    created_by: str | None
    created_at: str | None
    confirmed: int
    proposed: int


class ProgrammeList(BaseModel):
    programmes: list[Programme]


class ProgrammeMember(BaseModel):
    issuer_id: str
    company: str
    status: Literal["proposed", "confirmed", "ended"]
    proposed_by: str
    proposed_at: str
    confirmed_by: str | None
    confirmed_at: str | None
    ended_by: str | None
    ended_at: str | None
    end_reason: str | None


class ProgrammeDetail(Programme):
    members: list[ProgrammeMember]


class ProgrammeCreate(BaseModel):
    name: str


class ProgrammeMembersChange(BaseModel):
    add: list[str] = []
    remove: list[str] = []
    end: list[str] = []
    reason: str | None = None


class SuggestedIssue(BaseModel):
    issue_id: str
    fir_theme: str


class ProgrammeSuggestion(BaseModel):
    issuer_id: str
    company: str
    issues: list[SuggestedIssue]


class ProgrammeSuggestions(BaseModel):
    suggestions: list[ProgrammeSuggestion]
