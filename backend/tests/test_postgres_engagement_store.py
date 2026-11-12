import threading

import pytest
from sqlalchemy import func, select

from arp.db.session import transaction
from arp.errors import ClientInputError
from arp.schemas.common import now_iso
from arp.schemas.engagement import (
    ActivityType,
    Commitment,
    CommitmentStatus,
    Contact,
    CorrespondenceEntry,
    CorrespondenceType,
    EscalationStage,
    InfluenceLevel,
    InteractionType,
    IssueSeverity,
    IssueStatus,
    MilestoneStage,
    Objective,
    ObjectiveResult,
    ObjectiveStatus,
    ObjectiveType,
    Receptiveness,
    TriggerSource,
)
from arp.storage.engagement_store import EngagementStore
from arp.storage.postgres_engagement_store import PostgresEngagementStore
from arp.storage.postgres_models import StwActivityModel, StwEventModel
from arp.storage.safe_path import UnsafeIdentifierError


def _count(dsn, model):
    with transaction(dsn) as s:
        return s.scalar(select(func.count()).select_from(model))


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if not k.endswith(("_id", "_at", "date"))}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _script(store):
    store.get_or_create("C1", "Acme Corp", sector="Energy")
    _, issue = store.open_issue(
        "C1",
        "Acme Corp",
        theme="climate",
        severity=IssueSeverity.HIGH,
        source=TriggerSource.CONTROVERSY_SCREEN,
        source_detail="Spill",
    )
    store.add_correspondence(
        "C1",
        issue.issue_id,
        CorrespondenceEntry(type="letter", summary="Outreach.", logged_by="jane", interaction_type=InteractionType.INFORMATIONAL),
    )
    store.add_commitment("C1", issue.issue_id, Commitment(text="Publish a plan.", target_date="2027-01-01", recorded_by="jane"))
    store.set_milestone_stage("C1", issue.issue_id, MilestoneStage.CONTACTED, reason="Letter sent.")
    store.set_escalation_stage("C1", issue.issue_id, EscalationStage.JOINT_ENGAGEMENT, "jane.pm", reason="No reply.")
    return store.get("C1")


def test_parity_ignoring_ids(pg, tmp_path):
    file_rec = _script(EngagementStore(tmp_path))
    pg_store = PostgresEngagementStore(pg)
    pg_rec = _script(pg_store)
    assert _strip(pg_rec.model_dump()) == _strip(file_rec.model_dump())
    assert [e["event_type"] for e in pg_store.events("C1")] == [
        "record_created",
        "issue_opened",
        "correspondence_added",
        "commitment_added",
        "milestone_changed",
        "escalation_changed",
    ]


def test_children_round_trip_exactly(pg):
    store = PostgresEngagementStore(pg)
    _, issue = store.open_issue("C1", "Acme Corp", theme="climate")
    contacts = [Contact(name=f"Ann {i}", role="IR", email="a@x.com", phone="1", last_contacted_at=now_iso()) for i in range(3)]
    for c in contacts:
        store.add_contact("C1", c)
    entries = [
        CorrespondenceEntry(
            type=CorrespondenceType.CALL,
            summary="Call.",
            doc_ref="d",
            logged_by="jane",
            interaction_type=InteractionType.ADVOCACY_PRESSURE,
            is_initiation=True,
        ),
        CorrespondenceEntry(type=CorrespondenceType.OTHER, summary="AGM question.", activity_type=ActivityType.AGM_INTERVENTION),
    ]
    for e in entries:
        store.add_correspondence("C1", issue.issue_id, e)
    commitment = Commitment(text="Plan.", target_date="Q4 2027", recorded_by="jane")
    store.add_commitment("C1", issue.issue_id, commitment)
    record = store.update_commitment_status(
        "C1", issue.issue_id, commitment.commitment_id, CommitmentStatus.VERIFIED, validated_by="bob"
    )

    assert record.contacts == contacts
    got = record.issues[0]
    assert got.correspondence == entries
    assert got.commitments[0].model_dump(exclude={"status", "validated_by", "validated_at"}) == commitment.model_dump(
        exclude={"status", "validated_by", "validated_at"}
    )
    assert (got.commitments[0].status, got.commitments[0].validated_by) == ("verified", "bob")
    assert got.model_dump(exclude={"correspondence", "commitments"}) == issue.model_dump(
        exclude={"correspondence", "commitments"}
    )
    assert store.get("C1") == record


def test_objective_round_trip(pg):
    store = PostgresEngagementStore(pg)
    _, issue = store.open_issue("C1", "Acme Corp", theme="climate")
    first = Objective(description="Set targets.", objective_type=ObjectiveType.STRATEGIC)
    second = Objective(
        description="Disclose scope 3.",
        objective_type=ObjectiveType.TRANSPARENCY,
        status=ObjectiveStatus.CLOSED,
        result=ObjectiveResult.PARTIALLY_ACHIEVED,
        receptiveness=Receptiveness.GOOD,
        escalated=True,
        follows_objective_id=first.objective_id,
        started_at=now_iso(),
        target_date="2027-06-30",
        closed_at=now_iso(),
        outcome="Partial disclosure.",
        influence_level=InfluenceLevel.LIKELY_LOOP,
        influence_evidence="Board minutes.",
        evidence_url="https://example.com/r",
        source="api",
    )
    store.add_objective("C1", issue.issue_id, first)
    record = store.add_objective("C1", issue.issue_id, second)
    assert store.list_objectives("C1", issue.issue_id) == [first, second]
    assert record.issues[0].objectives == [first, second]

    events = _count(pg, StwEventModel)
    store.update_objective("C1", issue.issue_id, first.objective_id, description="Set targets.")  # unchanged
    assert _count(pg, StwEventModel) == events
    store.update_objective("C1", issue.issue_id, first.objective_id, status=ObjectiveStatus.IN_PROGRESS)
    assert store.list_objectives("C1", issue.issue_id)[0].status == ObjectiveStatus.IN_PROGRESS
    assert [e["event_type"] for e in store.events("C1")][-3:] == ["objective_added", "objective_added", "objective_updated"]


def test_concurrent_appends_all_land_with_one_event_each(pg):
    store = PostgresEngagementStore(pg)
    _, issue = store.open_issue("C1", "Acme Corp", theme="climate")
    before = _count(pg, StwEventModel)

    def write():
        for i in range(20):
            store.add_correspondence("C1", issue.issue_id, CorrespondenceEntry(type="email", summary=f"Email {i}."))

    threads = [threading.Thread(target=write) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(store.get("C1").issues[0].correspondence) == 40
    assert _count(pg, StwActivityModel) == 40
    assert _count(pg, StwEventModel) - before == 40


def test_lock_blocks_another_writer_until_commit(pg):
    store = PostgresEngagementStore(pg)
    _, issue = store.open_issue("C1", "Acme Corp", theme="climate")
    writer = threading.Thread(
        target=store.add_correspondence, args=("C1", issue.issue_id, CorrespondenceEntry(type="email", summary="Late."))
    )
    with store.lock("C1"):
        writer.start()
        writer.join(timeout=1)
        assert writer.is_alive()  # waiting on the advisory lock
    writer.join(timeout=10)
    assert not writer.is_alive()
    assert len(store.get("C1").issues[0].correspondence) == 1


def test_noop_write_adds_no_event(pg):
    store = PostgresEngagementStore(pg)
    _, issue = store.open_issue("C1", "Acme Corp", theme="climate")
    before = _count(pg, StwEventModel)
    store.set_issue_status("C1", issue.issue_id, IssueStatus.OPEN)
    store.get_or_create("C1", "Acme Corp")
    assert _count(pg, StwEventModel) == before


def test_non_iso_timestamp_is_a_client_error(pg):
    store = PostgresEngagementStore(pg)
    _, issue = store.open_issue("C1", "Acme Corp", theme="climate")
    with pytest.raises(ClientInputError, match="last_contacted_at"):
        store.add_contact("C1", Contact(name="Ann", role="IR", last_contacted_at="last week"))
    with pytest.raises(ClientInputError, match="date"):
        store.add_correspondence("C1", issue.issue_id, CorrespondenceEntry(type="call", summary="x", date="yesterday"))


def test_existing_id_is_a_client_error(pg):
    store = PostgresEngagementStore(pg)
    store.get_or_create("C1", "Acme Corp")
    store.get_or_create("C2", "Beta Corp")
    store.add_contact("C1", Contact(contact_id="cnt_1", name="Ann", role="IR"))
    with pytest.raises(ClientInputError, match="cnt_1"):
        store.add_contact("C2", Contact(contact_id="cnt_1", name="Bob", role="IR"))
    assert store.get("C2").contacts == []


def test_unsafe_company_id_is_rejected_like_the_file_store(pg, tmp_path):
    for store in (EngagementStore(tmp_path), PostgresEngagementStore(pg)):
        with pytest.raises(UnsafeIdentifierError):
            store.get("../etc")
        with pytest.raises(UnsafeIdentifierError):
            store.get_or_create("../etc", "Evil")
