from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from arp.schemas.common import Citation, new_id, now_iso


class ProposalType(StrEnum):
    DIRECTOR_ELECTION = "director_election"
    SAY_ON_PAY = "say_on_pay"
    AUDITOR_RATIFICATION = "auditor_ratification"
    SHAREHOLDER_RESOLUTION = "shareholder_resolution"
    MERGER_ACQUISITION = "merger_acquisition"
    CAPITAL_ACTION = "capital_action"
    OTHER = "other"


class VotePosition(StrEnum):
    FOR = "for"
    AGAINST = "against"
    ABSTAIN = "abstain"
    WITHHOLD = "withhold"


class Proposal(BaseModel):
    proposal_id: str = Field(default_factory=lambda: new_id("prop"))
    company_id: str
    meeting_id: str
    meeting_date: str | None = None
    proposal_number: str = Field(description="Ballot item number/label as printed on the proxy statement, e.g. '3'.")
    type: ProposalType
    sponsor: str = Field(description="'Management' for board-proposed items, or the filing shareholder's name.")
    resolution_text: str
    management_recommendation: VotePosition | None = None
    supporting_data: dict[str, str] = Field(
        default_factory=dict, description="Structured figures the Policy Application Agent's deterministic rules key off, e.g. {'non_audit_fee_ratio': '0.62'}."
    )
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    source_doc_id: str | None = None


class PolicyRecommendation(BaseModel):
    vote: VotePosition
    rationale: str
    policy_rule_id: str | None = Field(default=None, description="Deterministic rule that matched, if any; None means an LLM judgment call was made.")
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    engagement_alignment_flag: bool = Field(
        default=False, description="True if this recommendation conflicts with an open/escalated engagement issue for this company; forces mandatory human review regardless of confidence."
    )
    engagement_alignment_note: str | None = None


class HumanVoteDecision(BaseModel):
    vote: VotePosition
    decided_by: str
    decided_at: str = Field(default_factory=now_iso)
    override_note: str | None = None
    co_signed_by: str | None = Field(
        default=None, description="Second sign-off, required before casting when the recommendation carries an engagement_alignment_flag."
    )


class CastStatus(StrEnum):
    CONFIRMED = "confirmed"
    FAILED = "failed"


class CastConfirmation(BaseModel):
    platform: str
    cast_at: str = Field(default_factory=now_iso)
    confirmation_id: str = Field(default_factory=lambda: new_id("conf"))
    status: CastStatus = CastStatus.CONFIRMED
    detail: str | None = None


class VoteRecord(BaseModel):
    vote_record_id: str = Field(default_factory=lambda: new_id("vote"))
    run_id: str = ""
    proposal: Proposal
    policy_recommendation: PolicyRecommendation | None = None
    human_decision: HumanVoteDecision | None = None
    cast_confirmation: CastConfirmation | None = None


class CompanyBallot(BaseModel):
    company_id: str
    name: str
    meeting_id: str
    meeting_date: str | None = None
    votes: list[VoteRecord] = Field(default_factory=list)
    generated_at: str = Field(default_factory=now_iso)
