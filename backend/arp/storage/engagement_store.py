from __future__ import annotations

from pathlib import Path

from arp.schemas.common import now_iso
from arp.schemas.engagement import (
    Commitment,
    CommitmentStatus,
    Contact,
    CorrespondenceEntry,
    EngagementIssue,
    EngagementRecord,
    EscalationStage,
    IssueSeverity,
    IssueStatus,
    MilestoneStage,
    TriggerSource,
)


class EngagementStore:
    """File-based persistence for the engagement record store -- the single
    source of truth every sub-agent and the orchestrator read/write.

    Layout: `engagements/<company_id>/record.json` holds the current
    materialized state; `engagements/<company_id>/events.jsonl` is an
    append-only audit log of every mutation, in the same never-overwritten
    spirit as RunStore's review-decision log -- so "why is this issue at
    escalation stage 4" is always answerable from history, not just the
    current snapshot.
    """

    def __init__(self, engagements_dir: Path) -> None:
        self.engagements_dir = engagements_dir

    def _dir(self, company_id: str) -> Path:
        d = self.engagements_dir / company_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _record_path(self, company_id: str) -> Path:
        return self._dir(company_id) / "record.json"

    def _events_path(self, company_id: str) -> Path:
        return self._dir(company_id) / "events.jsonl"

    def _save(self, record: EngagementRecord) -> EngagementRecord:
        record = record.model_copy(update={"updated_at": now_iso()})
        self._record_path(record.company_id).write_text(record.model_dump_json(indent=2))
        return record

    def _log_event(self, company_id: str, event_type: str, detail: dict) -> None:
        from arp.storage.run_store import RunStore

        RunStore.append_jsonl(self._events_path(company_id), {"event_type": event_type, "at": now_iso(), **detail})

    def get(self, company_id: str) -> EngagementRecord | None:
        path = self._record_path(company_id)
        if not path.exists():
            return None
        return EngagementRecord.model_validate_json(path.read_text())

    def get_or_create(self, company_id: str, name: str, sector: str | None = None) -> EngagementRecord:
        existing = self.get(company_id)
        if existing is not None:
            return existing
        record = EngagementRecord(company_id=company_id, name=name, sector=sector)
        self._save(record)
        self._log_event(company_id, "record_created", {})
        return record

    def list_all(self) -> list[EngagementRecord]:
        if not self.engagements_dir.exists():
            return []
        records = []
        for d in sorted(self.engagements_dir.iterdir()):
            if not d.is_dir():
                continue
            record = self.get(d.name)
            if record is not None:
                records.append(record)
        return records

    def events(self, company_id: str) -> list[dict]:
        from arp.storage.run_store import RunStore

        return RunStore.read_jsonl(self._events_path(company_id))

    def _get_or_raise(self, company_id: str) -> EngagementRecord:
        record = self.get(company_id)
        if record is None:
            raise ValueError(f"Unknown company_id: {company_id}")
        return record

    def _find_issue(self, record: EngagementRecord, issue_id: str) -> EngagementIssue:
        for issue in record.issues:
            if issue.issue_id == issue_id:
                return issue
        raise ValueError(f"Unknown issue_id: {issue_id} for company {record.company_id}")

    def _replace_issue(self, record: EngagementRecord, updated: EngagementIssue) -> EngagementRecord:
        issues = [updated if i.issue_id == updated.issue_id else i for i in record.issues]
        return record.model_copy(update={"issues": issues})

    def add_contact(self, company_id: str, contact: Contact) -> EngagementRecord:
        record = self._get_or_raise(company_id)
        record = record.model_copy(update={"contacts": [*record.contacts, contact]})
        record = self._save(record)
        self._log_event(company_id, "contact_added", {"contact_id": contact.contact_id, "name": contact.name})
        return record

    def open_issue(
        self,
        company_id: str,
        name: str,
        *,
        theme: str,
        severity: IssueSeverity = IssueSeverity.MEDIUM,
        source: TriggerSource = TriggerSource.MANUAL,
        source_detail: str = "",
        sector: str | None = None,
    ) -> tuple[EngagementRecord, EngagementIssue]:
        record = self.get_or_create(company_id, name, sector)
        issue = EngagementIssue(theme=theme, severity=severity, source=source, source_detail=source_detail, tags=[theme])
        record = record.model_copy(update={"issues": [*record.issues, issue]})
        record = self._save(record)
        self._log_event(company_id, "issue_opened", {"issue_id": issue.issue_id, "theme": theme, "source": source.value})
        return record, issue

    def open_issues_for_theme(self, company_id: str, theme: str) -> list[EngagementIssue]:
        record = self.get(company_id)
        if record is None:
            return []
        return [i for i in record.issues if i.theme == theme and i.status not in (IssueStatus.RESOLVED, IssueStatus.CLOSED)]

    def set_issue_status(self, company_id: str, issue_id: str, status: IssueStatus) -> EngagementRecord:
        record = self._get_or_raise(company_id)
        issue = self._find_issue(record, issue_id)
        record = self._replace_issue(record, issue.model_copy(update={"status": status}))
        record = self._save(record)
        self._log_event(company_id, "issue_status_changed", {"issue_id": issue_id, "status": status.value})
        return record

    def add_correspondence(self, company_id: str, issue_id: str, entry: CorrespondenceEntry) -> EngagementRecord:
        record = self._get_or_raise(company_id)
        issue = self._find_issue(record, issue_id)
        issue = issue.model_copy(update={"correspondence": [*issue.correspondence, entry]})
        record = self._save(self._replace_issue(record, issue))
        self._log_event(company_id, "correspondence_added", {"issue_id": issue_id, "entry_id": entry.entry_id, "type": entry.type.value})
        return record

    def add_commitment(self, company_id: str, issue_id: str, commitment: Commitment) -> EngagementRecord:
        record = self._get_or_raise(company_id)
        issue = self._find_issue(record, issue_id)
        issue = issue.model_copy(update={"commitments": [*issue.commitments, commitment]})
        record = self._save(self._replace_issue(record, issue))
        self._log_event(company_id, "commitment_added", {"issue_id": issue_id, "commitment_id": commitment.commitment_id})
        return record

    def update_commitment_status(
        self, company_id: str, issue_id: str, commitment_id: str, status: CommitmentStatus, validated_by: str | None = None
    ) -> EngagementRecord:
        record = self._get_or_raise(company_id)
        issue = self._find_issue(record, issue_id)
        updated_commitments = [
            c.model_copy(update={"status": status, "validated_by": validated_by, "validated_at": now_iso()}) if c.commitment_id == commitment_id else c
            for c in issue.commitments
        ]
        if not any(c.commitment_id == commitment_id for c in issue.commitments):
            raise ValueError(f"Unknown commitment_id: {commitment_id}")
        issue = issue.model_copy(update={"commitments": updated_commitments})
        record = self._save(self._replace_issue(record, issue))
        self._log_event(company_id, "commitment_status_changed", {"issue_id": issue_id, "commitment_id": commitment_id, "status": status.value})
        return record

    def set_milestone_stage(self, company_id: str, issue_id: str, stage: MilestoneStage, reason: str = "") -> EngagementRecord:
        from arp.schemas.engagement import MilestoneTransition

        record = self._get_or_raise(company_id)
        issue = self._find_issue(record, issue_id)
        transition = MilestoneTransition(stage=stage, reason=reason)
        issue = issue.model_copy(update={"milestone_stage": stage, "milestone_history": [*issue.milestone_history, transition]})
        record = self._save(self._replace_issue(record, issue))
        self._log_event(company_id, "milestone_changed", {"issue_id": issue_id, "stage": stage.value, "reason": reason})
        return record

    def set_escalation_stage(self, company_id: str, issue_id: str, stage: EscalationStage, decided_by: str, reason: str = "") -> EngagementRecord:
        """The escalation-lever decision is a non-negotiable human checkpoint
        (see docs/ENGAGEMENT_VOTING_ARCHITECTURE.md #4) -- this method is
        never called by the orchestrator itself, only by a human-driven
        API/CLI action that supplies `decided_by`.
        """
        from arp.schemas.engagement import EscalationTransition

        record = self._get_or_raise(company_id)
        issue = self._find_issue(record, issue_id)
        transition = EscalationTransition(stage=stage, decided_by=decided_by, reason=reason)
        issue = issue.model_copy(update={"escalation_stage": stage, "escalation_history": [*issue.escalation_history, transition]})
        record = self._save(self._replace_issue(record, issue))
        self._log_event(company_id, "escalation_changed", {"issue_id": issue_id, "stage": stage.value, "decided_by": decided_by, "reason": reason})
        return record
