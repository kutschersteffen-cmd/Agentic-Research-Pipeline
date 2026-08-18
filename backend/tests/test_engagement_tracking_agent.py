from arp.engagement.tracking_agent import (
    log_commitment_verified,
    log_meeting_summary_validated,
    log_outreach_sent,
)
from arp.schemas.engagement import CommitmentStatus, IssueStatus, MilestoneStage, TriggerSource
from arp.storage.engagement_store import EngagementStore


def _open_issue(store):
    _record, issue = store.open_issue("C1", "Acme Corp", theme="climate", source=TriggerSource.MANUAL)
    return issue


def test_log_outreach_sent_advances_to_contacted(tmp_path):
    store = EngagementStore(tmp_path)
    issue = _open_issue(store)
    record = log_outreach_sent(store, "C1", issue.issue_id, "Sent opening letter.", "jane.pm")
    updated = record.issues[0]
    assert updated.milestone_stage == MilestoneStage.CONTACTED
    assert len(updated.correspondence) == 1


def test_log_meeting_summary_validated_with_commitments_advances_to_commitment_made(tmp_path):
    store = EngagementStore(tmp_path)
    issue = _open_issue(store)
    record = log_meeting_summary_validated(
        store, "C1", issue.issue_id, "Discussed transition plan.", ["Will publish a transition plan by Q4."], "jane.pm"
    )
    updated = record.issues[0]
    assert updated.milestone_stage == MilestoneStage.COMMITMENT_MADE
    assert len(updated.commitments) == 1
    assert updated.commitments[0].status == CommitmentStatus.OPEN


def test_log_meeting_summary_validated_without_commitments_advances_to_response_received(tmp_path):
    store = EngagementStore(tmp_path)
    issue = _open_issue(store)
    record = log_meeting_summary_validated(store, "C1", issue.issue_id, "Discussed, no firm commitments yet.", [], "jane.pm")
    updated = record.issues[0]
    assert updated.milestone_stage == MilestoneStage.RESPONSE_RECEIVED
    assert updated.commitments == []


def test_log_commitment_verified_resolves_issue_when_all_verified(tmp_path):
    store = EngagementStore(tmp_path)
    issue = _open_issue(store)
    record = log_meeting_summary_validated(store, "C1", issue.issue_id, "Meeting held.", ["Publish transition plan."], "jane.pm")
    commitment_id = record.issues[0].commitments[0].commitment_id

    record = log_commitment_verified(store, "C1", issue.issue_id, commitment_id, "jane.pm")
    updated = record.issues[0]
    assert updated.commitments[0].status == CommitmentStatus.VERIFIED
    assert updated.milestone_stage == MilestoneStage.COMMITMENT_VERIFIED
    assert updated.status == IssueStatus.RESOLVED


def test_log_commitment_verified_does_not_resolve_when_other_commitments_open(tmp_path):
    store = EngagementStore(tmp_path)
    issue = _open_issue(store)
    record = log_meeting_summary_validated(
        store, "C1", issue.issue_id, "Meeting held.", ["Publish transition plan.", "Appoint a board sponsor."], "jane.pm"
    )
    first_id = record.issues[0].commitments[0].commitment_id

    record = log_commitment_verified(store, "C1", issue.issue_id, first_id, "jane.pm")
    updated = record.issues[0]
    assert updated.milestone_stage == MilestoneStage.COMMITMENT_MADE
    assert updated.status == IssueStatus.OPEN
