from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from arp.schemas.common import Citation, new_id, now_iso


class MilestoneStage(StrEnum):
    """Illustrative 6-step engagement milestone framework -- swap for the
    house's actual stewardship framework; nothing downstream depends on
    these exact names, only on the fact that every issue has *some* current
    stage from an ordered progression (see arp.engagement.orchestrator)."""

    IDENTIFIED = "identified"
    CONTACTED = "contacted"
    DIALOGUE_OPENED = "dialogue_opened"
    RESPONSE_RECEIVED = "response_received"
    COMMITMENT_MADE = "commitment_made"
    COMMITMENT_VERIFIED = "commitment_verified"


MILESTONE_ORDER: list[MilestoneStage] = [
    MilestoneStage.IDENTIFIED,
    MilestoneStage.CONTACTED,
    MilestoneStage.DIALOGUE_OPENED,
    MilestoneStage.RESPONSE_RECEIVED,
    MilestoneStage.COMMITMENT_MADE,
    MilestoneStage.COMMITMENT_VERIFIED,
]


class EscalationStage(StrEnum):
    """Illustrative 7-step escalation ladder. Stage 5+ overlaps with the
    voting module: a decision to reach PRIVATE_ENGAGEMENT..ESCALATION_TO_CHAIR
    stays inside the engagement workflow, but VOTE_AGAINST_MANAGEMENT and
    beyond are the same decision the voting module's Policy Application
    Agent checks for alignment against (see arp.voting.policy_agent)."""

    PRIVATE_ENGAGEMENT = "private_engagement"
    JOINT_ENGAGEMENT = "joint_engagement"
    WRITTEN_ESCALATION_TO_BOARD = "written_escalation_to_board"
    ESCALATION_TO_CHAIR = "escalation_to_chair"
    VOTE_AGAINST_MANAGEMENT = "vote_against_management"
    FILE_OR_COFILE_RESOLUTION = "file_or_cofile_resolution"
    PUBLIC_STATEMENT = "public_statement"


ESCALATION_ORDER: list[EscalationStage] = [
    EscalationStage.PRIVATE_ENGAGEMENT,
    EscalationStage.JOINT_ENGAGEMENT,
    EscalationStage.WRITTEN_ESCALATION_TO_BOARD,
    EscalationStage.ESCALATION_TO_CHAIR,
    EscalationStage.VOTE_AGAINST_MANAGEMENT,
    EscalationStage.FILE_OR_COFILE_RESOLUTION,
    EscalationStage.PUBLIC_STATEMENT,
]


class IssueStatus(StrEnum):
    OPEN = "open"
    STALLED = "stalled"
    RESOLVED = "resolved"
    CLOSED = "closed"


class IssueSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TriggerSource(StrEnum):
    CONTROVERSY_SCREEN = "controversy_screen"
    ANALYST_RAISED = "analyst_raised"
    SLA_STALL = "sla_stall"
    MANUAL = "manual"


class CorrespondenceType(StrEnum):
    LETTER = "letter"
    CALL = "call"
    MEETING = "meeting"
    EMAIL = "email"
    OTHER = "other"


class CommitmentStatus(StrEnum):
    OPEN = "open"
    VERIFIED = "verified"
    MISSED = "missed"


class Contact(BaseModel):
    contact_id: str = Field(default_factory=lambda: new_id("cnt"))
    name: str
    role: str = Field(description="e.g. 'IR', 'Chair', 'Lead Independent Director'.")
    email: str | None = None
    phone: str | None = None
    last_contacted_at: str | None = None


class CorrespondenceEntry(BaseModel):
    entry_id: str = Field(default_factory=lambda: new_id("corr"))
    date: str = Field(default_factory=now_iso)
    type: CorrespondenceType
    summary: str
    doc_ref: str | None = Field(default=None, description="Path/URL to the letter, transcript, or notes document, if any.")
    logged_by: str | None = None


class Commitment(BaseModel):
    commitment_id: str = Field(default_factory=lambda: new_id("cmt"))
    text: str
    made_at: str = Field(default_factory=now_iso)
    target_date: str | None = None
    status: CommitmentStatus = CommitmentStatus.OPEN
    validated_by: str | None = None
    validated_at: str | None = None


class MilestoneTransition(BaseModel):
    stage: MilestoneStage
    changed_at: str = Field(default_factory=now_iso)
    reason: str = ""


class EscalationTransition(BaseModel):
    stage: EscalationStage
    changed_at: str = Field(default_factory=now_iso)
    decided_by: str
    reason: str = ""


class EngagementIssue(BaseModel):
    """One engagement thread on a company -- a company can have several
    concurrent issues (e.g. 'executive_compensation' and 'board_governance'
    open at once), each with its own milestone/escalation progression."""

    issue_id: str = Field(default_factory=lambda: new_id("iss"))
    theme: str = Field(description="Free-text theme/topic tag, e.g. 'executive_compensation', 'board_governance', 'climate_transition'.")
    opened_at: str = Field(default_factory=now_iso)
    status: IssueStatus = IssueStatus.OPEN
    severity: IssueSeverity = IssueSeverity.MEDIUM
    source: TriggerSource = TriggerSource.MANUAL
    source_detail: str = ""
    milestone_stage: MilestoneStage = MilestoneStage.IDENTIFIED
    milestone_history: list[MilestoneTransition] = Field(default_factory=list)
    escalation_stage: EscalationStage = EscalationStage.PRIVATE_ENGAGEMENT
    escalation_history: list[EscalationTransition] = Field(default_factory=list)
    correspondence: list[CorrespondenceEntry] = Field(default_factory=list)
    commitments: list[Commitment] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class EngagementRecord(BaseModel):
    """The single source of truth for one company's engagement state --
    every sub-agent and the orchestrator read/write this through
    arp.storage.engagement_store.EngagementStore, never a private copy."""

    company_id: str
    name: str
    sector: str | None = None
    contacts: list[Contact] = Field(default_factory=list)
    issues: list[EngagementIssue] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class TriggerEvent(BaseModel):
    trigger_id: str = Field(default_factory=lambda: new_id("trg"))
    company_id: str
    theme: str
    source: TriggerSource
    severity: IssueSeverity
    detail: str = ""
    detected_at: str = Field(default_factory=now_iso)
    raised_issue_id: str | None = None


# ---- Research Agent output ------------------------------------------------


class ResearchDossier(BaseModel):
    dossier_id: str = Field(default_factory=lambda: new_id("dos"))
    company_id: str
    issue_id: str
    generated_at: str = Field(default_factory=now_iso)
    summary: str
    controversy_context: str
    peer_benchmark_notes: str
    engagement_history_summary: str
    recommended_contacts: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    needs_review: bool = False


# ---- Drafting Agent outputs -------------------------------------------------


class OutreachLetterDraft(BaseModel):
    subject: str
    body: str
    recommended_recipient: str
    citations: list[Citation] = Field(default_factory=list)


class MeetingTalkingPoints(BaseModel):
    objectives: list[str]
    points: list[str]


class MeetingSummaryDraft(BaseModel):
    summary: str
    commitments_identified: list[str] = Field(default_factory=list, description="Plain-language commitment texts, if any were made in the meeting.")
    follow_up_actions: list[str] = Field(default_factory=list)
