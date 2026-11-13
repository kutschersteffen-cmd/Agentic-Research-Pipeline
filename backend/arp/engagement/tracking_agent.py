from __future__ import annotations

from datetime import UTC, datetime

from arp.schemas.engagement import (
    Commitment,
    CommitmentStatus,
    CorrespondenceEntry,
    EngagementRecord,
    IssueStatus,
    MilestoneStage,
)
from arp.storage.engagement_store import EngagementStore

"""Non-LLM logic: logs outcomes and advances milestone state on the record
store. No sub-agent here talks to a model -- this is deliberately
mechanical bookkeeping, kept separate from Research/Drafting so a bug in an
LLM prompt can never silently corrupt milestone state.
"""


def log_outreach_sent(
    store: EngagementStore, company_id: str, issue_id: str, summary: str, sent_by: str, doc_ref: str | None = None
) -> EngagementRecord:
    """Called only after the human send-authorization checkpoint has
    already happened -- this function has no opinion on authorization, it
    just records that outreach went out and advances the milestone."""
    record = store.get(company_id)
    issue = next((i for i in record.issues if i.issue_id == issue_id), None) if record else None
    if issue and any(c.type == "letter" and c.summary == summary and c.doc_ref == doc_ref for c in issue.correspondence):
        return record  # the same letter logged again: nothing new happened
    store.add_correspondence(
        company_id,
        issue_id,
        CorrespondenceEntry(type="letter", summary=summary, doc_ref=doc_ref, logged_by=sent_by),
    )
    return store.set_milestone_stage(
        company_id, issue_id, MilestoneStage.CONTACTED, reason=f"Outreach sent by {sent_by}.", forward_only=True
    )


def log_meeting_summary_validated(
    store: EngagementStore,
    company_id: str,
    issue_id: str,
    summary: str,
    commitments: list[str],
    validated_by: str,
) -> EngagementRecord:
    """Called only after the human meeting-notes-validation checkpoint --
    logs the validated summary as correspondence and, if the human-approved
    summary named any commitments, logs each one and advances the
    milestone to COMMITMENT_MADE; otherwise advances to RESPONSE_RECEIVED.
    """
    store.add_correspondence(
        company_id, issue_id, CorrespondenceEntry(type="meeting", summary=summary, logged_by=validated_by)
    )
    for text in commitments:
        store.add_commitment(company_id, issue_id, Commitment(text=text))
    stage = MilestoneStage.COMMITMENT_MADE if commitments else MilestoneStage.RESPONSE_RECEIVED
    reason = f"Meeting notes validated by {validated_by}." + (f" {len(commitments)} commitment(s) logged." if commitments else "")
    return store.set_milestone_stage(company_id, issue_id, stage, reason=reason, forward_only=True)


EVIDENCE_MSG = "Evidence is required to verify a commitment."


class MissingEvidence(ValueError):
    pass


def check_evidence(record: EngagementRecord | None, issue_id: str, commitment_id: str, evidence: str | None) -> None:
    """Raises MissingEvidence for a blank `evidence`, or for none on a commitment whose target date is
    after today (UTC). A missing one on a due or undated commitment passes (spec showcase-stewardship-fixes B2)."""
    if evidence is not None:
        if not evidence.strip():
            raise MissingEvidence(EVIDENCE_MSG)
        return
    issue = next((i for i in record.issues if i.issue_id == issue_id), None) if record else None
    commitment = next((c for c in issue.commitments if c.commitment_id == commitment_id), None) if issue else None
    if commitment and commitment.target_date and commitment.target_date[:10] > datetime.now(UTC).date().isoformat():
        raise MissingEvidence(EVIDENCE_MSG)


def log_commitment_verified(
    store: EngagementStore, company_id: str, issue_id: str, commitment_id: str, verified_by: str, evidence: str | None = None
) -> EngagementRecord:
    check_evidence(store.get(company_id), issue_id, commitment_id, evidence)
    record = store.update_commitment_status(
        company_id, issue_id, commitment_id, CommitmentStatus.VERIFIED, verified_by, evidence
    )
    issue = next(i for i in record.issues if i.issue_id == issue_id)
    if issue.commitments and all(c.status == CommitmentStatus.VERIFIED for c in issue.commitments):
        record = store.set_milestone_stage(
            company_id, issue_id, MilestoneStage.COMMITMENT_VERIFIED, reason="All commitments verified."
        )
        record = store.set_issue_status(company_id, issue_id, IssueStatus.RESOLVED)
    return record
