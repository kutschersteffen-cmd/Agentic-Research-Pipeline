from datetime import datetime, timedelta, timezone

from arp.engagement.orchestrator import OrchestratorAction, decide_next_action, is_stalled, next_escalation_stage, next_milestone_stage
from arp.schemas.engagement import EngagementIssue, EscalationStage, IssueStatus, MilestoneStage, MilestoneTransition, TriggerSource


def _issue(**overrides) -> EngagementIssue:
    defaults = dict(theme="climate", source=TriggerSource.MANUAL)
    defaults.update(overrides)
    return EngagementIssue(**defaults)


def test_next_milestone_stage_progresses_in_order():
    assert next_milestone_stage(MilestoneStage.IDENTIFIED) == MilestoneStage.CONTACTED
    assert next_milestone_stage(MilestoneStage.COMMITMENT_VERIFIED) is None


def test_next_escalation_stage_progresses_in_order():
    assert next_escalation_stage(EscalationStage.PRIVATE_ENGAGEMENT) == EscalationStage.JOINT_ENGAGEMENT
    assert next_escalation_stage(EscalationStage.PUBLIC_STATEMENT) is None


def test_decide_next_action_identified_dispatches_research():
    decision = decide_next_action(_issue(), sla_days=45)
    assert decision.action == OrchestratorAction.DISPATCH_RESEARCH


def test_decide_next_action_contacted_awaits_response():
    issue = _issue(milestone_stage=MilestoneStage.CONTACTED)
    decision = decide_next_action(issue, sla_days=45)
    assert decision.action == OrchestratorAction.AWAIT_RESPONSE


def test_decide_next_action_response_received_dispatches_drafting_summary():
    issue = _issue(milestone_stage=MilestoneStage.RESPONSE_RECEIVED)
    decision = decide_next_action(issue, sla_days=45)
    assert decision.action == OrchestratorAction.DISPATCH_DRAFTING_SUMMARY


def test_decide_next_action_terminal_status_is_no_action():
    issue = _issue(status=IssueStatus.RESOLVED, milestone_stage=MilestoneStage.COMMITMENT_MADE)
    decision = decide_next_action(issue, sla_days=45)
    assert decision.action == OrchestratorAction.NO_ACTION


def test_is_stalled_false_for_recent_activity():
    issue = _issue(opened_at=datetime.now(timezone.utc).isoformat())
    assert is_stalled(issue, sla_days=45) is False


def test_is_stalled_true_past_sla_with_no_activity():
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    issue = _issue(opened_at=old)
    assert is_stalled(issue, sla_days=45) is True


def test_is_stalled_uses_latest_milestone_transition_not_opened_at():
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    recent = datetime.now(timezone.utc).isoformat()
    issue = _issue(opened_at=old, milestone_history=[MilestoneTransition(stage=MilestoneStage.CONTACTED, changed_at=recent)])
    assert is_stalled(issue, sla_days=45) is False


def test_decide_next_action_stalled_overrides_milestone_action():
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    issue = _issue(opened_at=old, milestone_stage=MilestoneStage.CONTACTED)
    decision = decide_next_action(issue, sla_days=45)
    assert decision.action == OrchestratorAction.FLAG_FOR_ESCALATION_DECISION


def test_is_stalled_never_true_for_resolved_issue():
    old = (datetime.now(timezone.utc) - timedelta(days=900)).isoformat()
    issue = _issue(opened_at=old, status=IssueStatus.RESOLVED)
    assert is_stalled(issue, sla_days=45) is False
