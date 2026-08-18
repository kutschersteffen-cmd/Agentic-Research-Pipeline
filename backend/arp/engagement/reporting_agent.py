from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from arp.engagement.orchestrator import escalation_index
from arp.schemas.engagement import EngagementRecord, EscalationStage, IssueStatus
from arp.schemas.voting import VoteRecord

"""Reporting Agent: periodic, non-LLM aggregation over the engagement
record store and voting run results for quarterly/annual stewardship
disclosure (e.g. PDCA-style reporting). No agent call is needed here --
every number is a deterministic rollup of already-decided, already-audited
state, which is exactly what a disclosure report should be."""


class EngagementStats(BaseModel):
    total_issues: int = 0
    open_issues: int = 0
    stalled_issues: int = 0
    resolved_issues: int = 0
    closed_issues: int = 0
    by_milestone_stage: dict[str, int] = Field(default_factory=dict)
    by_escalation_stage: dict[str, int] = Field(default_factory=dict)
    commitments_open: int = 0
    commitments_verified: int = 0
    commitments_missed: int = 0


class VoteStats(BaseModel):
    total_votes: int = 0
    cast_votes: int = 0
    by_position: dict[str, int] = Field(default_factory=dict)
    overrides: int = Field(default=0, description="Votes cast that differ from the policy recommendation.")
    alignment_flags_total: int = 0
    alignment_flags_cast: int = 0


class EscalationLinkedVote(BaseModel):
    company_id: str
    issue_id: str
    escalation_stage: str
    vote_record_id: str
    proposal_id: str
    vote: str


class StewardshipReport(BaseModel):
    period_label: str
    engagement_stats: EngagementStats
    vote_stats: VoteStats
    escalation_linked_votes: list[EscalationLinkedVote] = Field(default_factory=list)


def compile_engagement_stats(records: list[EngagementRecord]) -> EngagementStats:
    stats = EngagementStats()
    milestone_counter: Counter[str] = Counter()
    escalation_counter: Counter[str] = Counter()
    for record in records:
        for issue in record.issues:
            stats.total_issues += 1
            if issue.status == IssueStatus.OPEN:
                stats.open_issues += 1
            elif issue.status == IssueStatus.STALLED:
                stats.stalled_issues += 1
            elif issue.status == IssueStatus.RESOLVED:
                stats.resolved_issues += 1
            elif issue.status == IssueStatus.CLOSED:
                stats.closed_issues += 1
            milestone_counter[issue.milestone_stage.value] += 1
            escalation_counter[issue.escalation_stage.value] += 1
            for commitment in issue.commitments:
                if commitment.status.value == "open":
                    stats.commitments_open += 1
                elif commitment.status.value == "verified":
                    stats.commitments_verified += 1
                elif commitment.status.value == "missed":
                    stats.commitments_missed += 1
    stats.by_milestone_stage = dict(milestone_counter)
    stats.by_escalation_stage = dict(escalation_counter)
    return stats


def compile_vote_stats(vote_records: list[VoteRecord]) -> VoteStats:
    stats = VoteStats(total_votes=len(vote_records))
    position_counter: Counter[str] = Counter()
    for vr in vote_records:
        if vr.human_decision is None:
            continue
        stats.cast_votes += 1
        position_counter[vr.human_decision.vote.value] += 1
        if vr.policy_recommendation is not None and vr.human_decision.vote != vr.policy_recommendation.vote:
            stats.overrides += 1
        if vr.policy_recommendation is not None and vr.policy_recommendation.engagement_alignment_flag:
            stats.alignment_flags_cast += 1
    stats.alignment_flags_total = sum(
        1 for vr in vote_records if vr.policy_recommendation is not None and vr.policy_recommendation.engagement_alignment_flag
    )
    stats.by_position = dict(position_counter)
    return stats


def escalation_linked_votes(records: list[EngagementRecord], vote_records: list[VoteRecord]) -> list[EscalationLinkedVote]:
    """The explicit narrative link stewardship codes increasingly expect:
    every cast vote for a company that also has an issue escalated to
    VOTE_AGAINST_MANAGEMENT or beyond, so a report can show the connection
    between "we escalated" and "we voted" rather than two disconnected
    figures."""
    records_by_id = {r.company_id: r for r in records}
    threshold = escalation_index(EscalationStage.VOTE_AGAINST_MANAGEMENT)
    linked: list[EscalationLinkedVote] = []
    for vr in vote_records:
        if vr.human_decision is None:
            continue
        record = records_by_id.get(vr.proposal.company_id)
        if record is None:
            continue
        for issue in record.issues:
            if escalation_index(issue.escalation_stage) >= threshold:
                linked.append(
                    EscalationLinkedVote(
                        company_id=record.company_id,
                        issue_id=issue.issue_id,
                        escalation_stage=issue.escalation_stage.value,
                        vote_record_id=vr.vote_record_id,
                        proposal_id=vr.proposal.proposal_id,
                        vote=vr.human_decision.vote.value,
                    )
                )
    return linked


def compile_report(records: list[EngagementRecord], vote_records: list[VoteRecord], period_label: str) -> StewardshipReport:
    return StewardshipReport(
        period_label=period_label,
        engagement_stats=compile_engagement_stats(records),
        vote_stats=compile_vote_stats(vote_records),
        escalation_linked_votes=escalation_linked_votes(records, vote_records),
    )
