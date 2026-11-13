import pytest

from arp.schemas.engagement import (
    Commitment,
    CommitmentStatus,
    CorrespondenceEntry,
    EscalationStage,
    IssueSeverity,
    IssueStatus,
    MilestoneStage,
    TriggerSource,
)
from arp.storage.engagement_store import EngagementStore


@pytest.fixture(params=["file", "postgres"])
def store(request, tmp_path):
    if request.param == "file":
        return EngagementStore(tmp_path)
    from arp.storage.postgres_engagement_store import PostgresEngagementStore

    return PostgresEngagementStore(request.getfixturevalue("pg"))


def test_get_or_create_is_idempotent(store):
    a = store.get_or_create("C1", "Acme Corp")
    b = store.get_or_create("C1", "Acme Corp (renamed elsewhere)")
    assert a.name == b.name == "Acme Corp"


def test_open_issue_creates_record_and_issue(store):
    record, issue = store.open_issue("C1", "Acme Corp", theme="board_governance", severity=IssueSeverity.HIGH, source=TriggerSource.MANUAL)
    assert record.company_id == "C1"
    assert issue.theme == "board_governance"
    assert issue.milestone_stage == MilestoneStage.IDENTIFIED
    assert issue.escalation_stage == EscalationStage.PRIVATE_ENGAGEMENT

    reloaded = store.get("C1")
    assert len(reloaded.issues) == 1
    assert reloaded.issues[0].issue_id == issue.issue_id


def test_open_issues_for_theme_excludes_resolved_and_closed(store):
    _record, issue = store.open_issue("C1", "Acme Corp", theme="climate", source=TriggerSource.MANUAL)
    assert store.open_issues_for_theme("C1", "climate") == [issue]

    store.set_issue_status("C1", issue.issue_id, IssueStatus.RESOLVED)
    assert store.open_issues_for_theme("C1", "climate") == []


def test_set_milestone_stage_appends_history(store):
    _record, issue = store.open_issue("C1", "Acme Corp", theme="climate", source=TriggerSource.MANUAL)
    record = store.set_milestone_stage("C1", issue.issue_id, MilestoneStage.CONTACTED, reason="Outreach sent.")
    updated = record.issues[0]
    assert updated.milestone_stage == MilestoneStage.CONTACTED
    assert len(updated.milestone_history) == 1
    assert updated.milestone_history[0].reason == "Outreach sent."


def test_set_escalation_stage_requires_decided_by_and_logs_it(store):
    _record, issue = store.open_issue("C1", "Acme Corp", theme="climate", source=TriggerSource.MANUAL)
    record = store.set_escalation_stage("C1", issue.issue_id, EscalationStage.JOINT_ENGAGEMENT, "jane.pm", reason="No response after 60 days.")
    updated = record.issues[0]
    assert updated.escalation_stage == EscalationStage.JOINT_ENGAGEMENT
    assert updated.escalation_history[0].decided_by == "jane.pm"


def test_add_correspondence_and_commitment(store):
    _record, issue = store.open_issue("C1", "Acme Corp", theme="climate", source=TriggerSource.MANUAL)
    store.add_correspondence("C1", issue.issue_id, CorrespondenceEntry(type="call", summary="Intro call held."))
    record = store.add_commitment("C1", issue.issue_id, Commitment(text="Will publish a transition plan by Q4."))
    updated = record.issues[0]
    assert len(updated.correspondence) == 1
    assert len(updated.commitments) == 1
    assert updated.commitments[0].status == CommitmentStatus.OPEN


def test_update_commitment_status_unknown_commitment_raises(store):
    _record, issue = store.open_issue("C1", "Acme Corp", theme="climate", source=TriggerSource.MANUAL)
    with pytest.raises(ValueError):
        store.update_commitment_status("C1", issue.issue_id, "cmt_nope", CommitmentStatus.VERIFIED)


def test_events_log_is_append_only_audit_trail(store):
    _record, issue = store.open_issue("C1", "Acme Corp", theme="climate", source=TriggerSource.MANUAL)
    store.set_milestone_stage("C1", issue.issue_id, MilestoneStage.CONTACTED)
    store.set_escalation_stage("C1", issue.issue_id, EscalationStage.JOINT_ENGAGEMENT, "jane.pm")

    events = store.events("C1")
    event_types = [e["event_type"] for e in events]
    assert event_types == ["record_created", "issue_opened", "milestone_changed", "escalation_changed"]


def test_get_unknown_company_returns_none(store):
    assert store.get("nope") is None


def test_mutating_unknown_company_raises(store):
    with pytest.raises(ValueError):
        store.set_issue_status("nope", "iss_nope", IssueStatus.CLOSED)


def test_api_and_cli_build_the_store_on_the_engagements_dir(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from arp.api import deps
    from arp.cli import _shared

    settings = SimpleNamespace(engagement_store="file", engagements_dir=tmp_path / "engagements")
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    monkeypatch.setattr(_shared, "get_settings", lambda: settings)
    assert deps.get_engagement_store.__wrapped__().engagements_dir == settings.engagements_dir
    assert _shared._engagement_store().engagements_dir == settings.engagements_dir
