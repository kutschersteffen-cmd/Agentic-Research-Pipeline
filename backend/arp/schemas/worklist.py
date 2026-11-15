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


class Engaged(BaseModel):
    yes: bool
    last: str | None


class HeldIn(BaseModel):
    portfolio_id: str
    name: str
    weight_pct: float | None
    market_value_eur_m: float
    selection_status: Literal["proposed", "confirmed"] | None


class SelectedElsewhere(BaseModel):
    scope: str
    label: str
    status: Literal["proposed", "confirmed"]


class LatestNote(BaseModel):
    text: str
    by: str
    at: str


class NotesSummary(BaseModel):
    count: int
    latest: LatestNote | None


class WorklistRow(BaseModel):
    issuer_id: str
    company: str
    sector: str
    identifier: str
    engaged: Engaged
    last_topics: list[str]
    norms_violation: Observed | None
    esg_extra: dict[str, Observed]
    equity_held_eur_m: float
    ownership_pct: Observed | None
    holdings_weight_pct: float | None
    aum_held_eur_m: float | None
    coverage_tier: str
    coverage_tier_confirmed: bool
    triggers: TriggerCounts
    new_high_trigger: bool
    open_engagements: int
    escalated: int
    overdue_commitments: int
    broken_commitments: int
    next_meeting: NextMeeting | None
    transition_grade: Grade | None
    esg_score: Observed | None
    controversy: Observed | None
    carbon_intensity: Observed | None
    score: float
    parts: list[ScorePart]
    selection: Selection | None
    programmes: list[ProgrammeChip]
    held_in: list[HeldIn]
    selected_elsewhere: list[SelectedElsewhere]
    notes: NotesSummary


class WorklistScope(BaseModel):
    key: str
    label: str
    kind: str
    companies: int


class WorklistScopes(BaseModel):
    scopes: list[WorklistScope]


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
    scope: str = "house"
    add: list[str] = []
    remove: list[str] = []


class SelectionConfirm(BaseModel):
    cycle: str | None = None
    scope: str = "house"


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


class NoteCreate(BaseModel):
    company_id: str
    text: str
    scope: str = "house"


class Note(BaseModel):
    note_id: str
    company_id: str
    text: str
    by: str
    at: str
    scope: str


class NoteList(BaseModel):
    notes: list[Note]


class Vote(BaseModel):
    meeting_date: str | None
    meeting_type: str | None
    item_number: str | None
    description: str | None
    proponent: str | None
    management_recommendation: str | None
    vote: str
    vote_label: str | None
    against_management: bool | None
    rationale: str | None
    source: str
    demo: bool


class VoteList(BaseModel):
    votes: list[Vote]
    total: int
