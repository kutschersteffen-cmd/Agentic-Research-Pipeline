from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

from arp.api.routers.stewardship import (
    CloseRequest,
    CommitmentRequest,
    CommitmentStatusRequest,
    add_commitment,
    close_engagement,
    get_case_study,
    set_commitment_status,
)
from arp.schemas.engagement import CorrespondenceEntry, EscalationStage, InteractionType, IssueStatus
from arp.stewardship import tracking
from arp.stewardship.process import HOUSE, StreamStore, flow
from arp.storage.engagement_store import EngagementStore
from tests.conftest import PRINCIPAL

TODAY = date(2026, 9, 27)


@pytest.fixture
def world(tmp_path):
    engagements = EngagementStore(tmp_path / "e")
    _, issue = engagements.open_issue("ACME", "Acme", theme="climate_transition")
    return engagements, StreamStore(tmp_path / "s"), issue


def _commit(engagements, issue, text, target):
    return add_commitment(
        CommitmentRequest(company_id="ACME", issue_id=issue.issue_id, text=text, target_date=target),
        engagements,
        PRINCIPAL,
    )


def test_overdue_and_missed_commitments_and_stalls_become_triggers(world):
    engagements, _, issue = world
    _commit(engagements, issue, "Publish interim targets", "2026-06-30")
    missed = _commit(engagements, issue, "Report scope 3", "2027-01-01")
    _commit(engagements, issue, "Not due yet", "2027-06-30")
    set_commitment_status(
        missed["commitment_id"],
        CommitmentStatusRequest(company_id="ACME", issue_id=issue.issue_id, status="missed"),
        engagements,
        PRINCIPAL,
    )
    rules = sorted(t["rule"] for t in tracking.triggers(engagements.list_all(), sla_days=365, today=TODAY))
    assert rules == ["commitment_missed", "commitment_overdue"]
    assert all(t["engagement_id"] == issue.issue_id for t in tracking.triggers(engagements.list_all(), 365, TODAY))
    assert "engagement_stalled" in {t["rule"] for t in tracking.triggers(engagements.list_all(), sla_days=-1, today=TODAY)}
    [due] = [c for c in tracking.commitments(engagements.list_all(), TODAY) if c["overdue"]]
    assert due["text"] == "Publish interim targets"


def test_stage_1_and_6_show_the_tracking_loop(world):
    engagements, streams, issue = world
    _commit(engagements, issue, "Publish interim targets", "2020-01-01")
    stages = {s["id"]: s for s in flow(HOUSE, streams, engagements.list_all(), sla_days=365)["stages"]}
    assert {m["label"]: m["value"] for m in stages["monitoring"]["metrics"]}["Tracking triggers"] == 1
    [due] = stages["tracking"]["decisions"]
    assert (due["kind"], due["text"]) == ("commitment_due", "Publish interim targets")


def test_invalid_target_date_and_unknown_engagement_are_rejected(world):
    engagements, _, issue = world
    with pytest.raises(HTTPException) as bad_date:
        _commit(engagements, issue, "x", "next spring")
    assert bad_date.value.status_code == 422
    with pytest.raises(HTTPException) as unknown:
        add_commitment(CommitmentRequest(company_id="NOPE", issue_id="x", text="x"), engagements, PRINCIPAL)
    assert unknown.value.status_code == 404


def test_a_closed_engagement_gets_a_case_study_from_its_records_with_style_flags(world):
    engagements, streams, issue = world
    with pytest.raises(HTTPException) as still_open:
        get_case_study("ACME", issue.issue_id, streams, engagements)
    assert still_open.value.status_code == 422
    engagements.set_escalation_stage("ACME", issue.issue_id, EscalationStage.JOINT_ENGAGEMENT, "Lead")
    kept = _commit(engagements, issue, "Publish interim targets", "2026-06-30")
    set_commitment_status(
        kept["commitment_id"],
        CommitmentStatusRequest(company_id="ACME", issue_id=issue.issue_id, status="verified"),
        engagements,
        PRINCIPAL,
    )
    engagements.add_correspondence(
        "ACME",
        issue.issue_id,
        CorrespondenceEntry(type="letter", summary="x", interaction_type=InteractionType.ADVOCACY_PRESSURE),
    )
    close_engagement(
        CloseRequest(
            company_id="ACME",
            issue_id=issue.issue_id,
            status="resolved",
            outcome="Thanks to our engagement the board set interim targets.",
        ),
        engagements,
        PRINCIPAL,
    )
    assert engagements.get("ACME").issues[0].status == IssueStatus.RESOLVED
    study = get_case_study("ACME", issue.issue_id, streams, engagements)
    assert "joint engagement (decided by Lead)" in study["text"]
    assert "1 letter (advocacy pressure)" in study["text"]
    assert "Kept: Publish interim targets" in study["text"]
    assert study["text"].endswith("Outcome. Resolved: Thanks to our engagement the board set interim targets.")
    assert [f["phrase"] for f in study["style_flags"]] == ["thanks to our engagement"]  # the outcome wording is checked too
    with pytest.raises(HTTPException) as twice:
        close_engagement(
            CloseRequest(company_id="ACME", issue_id=issue.issue_id, status="closed", outcome="x"), engagements, PRINCIPAL
        )
    assert twice.value.status_code == 422
