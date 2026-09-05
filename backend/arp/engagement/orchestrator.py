from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel

from arp.schemas.engagement import (
    ESCALATION_ORDER,
    MILESTONE_ORDER,
    EngagementIssue,
    EscalationStage,
    IssueStatus,
    MilestoneStage,
)


class OrchestratorAction(StrEnum):
    """The controller's dispatch decision for one issue. Owning this mapping
    centrally (here) rather than scattering "what happens next" logic across
    sub-agents is the whole point of having an orchestrator -- see
    docs/ENGAGEMENT_VOTING_ARCHITECTURE.md #2."""

    DISPATCH_RESEARCH = "dispatch_research"
    AWAIT_RESPONSE = "await_response"
    DISPATCH_DRAFTING_SUMMARY = "dispatch_drafting_summary"
    AWAIT_COMMITMENT_TARGET_DATE = "await_commitment_target_date"
    FLAG_FOR_ESCALATION_DECISION = "flag_for_escalation_decision"
    NO_ACTION = "no_action"


class OrchestratorDecision(BaseModel):
    action: OrchestratorAction
    reason: str


_ACTION_BY_MILESTONE: dict[MilestoneStage, OrchestratorAction] = {
    MilestoneStage.IDENTIFIED: OrchestratorAction.DISPATCH_RESEARCH,
    MilestoneStage.CONTACTED: OrchestratorAction.AWAIT_RESPONSE,
    MilestoneStage.DIALOGUE_OPENED: OrchestratorAction.AWAIT_RESPONSE,
    MilestoneStage.RESPONSE_RECEIVED: OrchestratorAction.DISPATCH_DRAFTING_SUMMARY,
    MilestoneStage.COMMITMENT_MADE: OrchestratorAction.AWAIT_COMMITMENT_TARGET_DATE,
    MilestoneStage.COMMITMENT_VERIFIED: OrchestratorAction.NO_ACTION,
}

_TERMINAL_STATUSES = (IssueStatus.RESOLVED, IssueStatus.CLOSED)


def next_milestone_stage(current: MilestoneStage) -> MilestoneStage | None:
    idx = MILESTONE_ORDER.index(current)
    return MILESTONE_ORDER[idx + 1] if idx + 1 < len(MILESTONE_ORDER) else None


def next_escalation_stage(current: EscalationStage) -> EscalationStage | None:
    idx = ESCALATION_ORDER.index(current)
    return ESCALATION_ORDER[idx + 1] if idx + 1 < len(ESCALATION_ORDER) else None


def escalation_index(stage: EscalationStage) -> int:
    return ESCALATION_ORDER.index(stage)


def _last_activity_at(issue: EngagementIssue) -> str:
    timestamps = [issue.opened_at]
    timestamps += [t.changed_at for t in issue.milestone_history]
    timestamps += [t.changed_at for t in issue.escalation_history]
    timestamps += [c.date for c in issue.correspondence]
    return max(timestamps)


def is_stalled(issue: EngagementIssue, sla_days: int, now: datetime | None = None) -> bool:
    """True when an open issue has had no recorded activity (milestone
    change, escalation change, or correspondence) for longer than
    `sla_days`. Resolved/closed issues are never stalled."""
    if issue.status in _TERMINAL_STATUSES:
        return False
    now = now or datetime.now(UTC)
    last = datetime.fromisoformat(_last_activity_at(issue))
    return (now - last).days >= sla_days


def decide_next_action(issue: EngagementIssue, sla_days: int, now: datetime | None = None) -> OrchestratorDecision:
    """The orchestrator's core state-machine call: given one issue's current
    state, what should happen next. Escalation is deliberately never decided
    here -- FLAG_FOR_ESCALATION_DECISION routes to a human, who is the only
    one that can move `escalation_stage` (see EngagementStore.set_escalation_stage).
    """
    if issue.status in _TERMINAL_STATUSES:
        return OrchestratorDecision(action=OrchestratorAction.NO_ACTION, reason=f"Issue is {issue.status.value}.")
    if is_stalled(issue, sla_days, now):
        return OrchestratorDecision(
            action=OrchestratorAction.FLAG_FOR_ESCALATION_DECISION,
            reason=f"No activity for >= {sla_days} days at milestone '{issue.milestone_stage.value}'; overdue against SLA.",
        )
    action = _ACTION_BY_MILESTONE[issue.milestone_stage]
    return OrchestratorDecision(action=action, reason=f"Milestone stage is '{issue.milestone_stage.value}'.")
