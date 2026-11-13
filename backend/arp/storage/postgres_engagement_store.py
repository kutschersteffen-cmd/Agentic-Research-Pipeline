"""Postgres engagement store (spec "Store and callers"): the same public surface as the file-based
EngagementStore, on the stw_* tables, plus VOICE objectives. Every write that changes data adds one
stw_events row; a write that changes nothing adds none."""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import DateTime, func, inspect, select, text
from sqlalchemy.orm import Session

from arp.db.session import transaction
from arp.errors import ClientInputError
from arp.schemas.common import new_id, now_iso
from arp.schemas.engagement import (
    Commitment,
    CommitmentStatus,
    Contact,
    CorrespondenceEntry,
    CorrespondenceType,
    EngagementIssue,
    EngagementRecord,
    EscalationStage,
    EscalationTransition,
    IssueSeverity,
    IssueStatus,
    MilestoneStage,
    MilestoneTransition,
    Objective,
    TriggerSource,
)
from arp.storage.postgres_models import (
    StwActivityModel,
    StwCommitmentModel,
    StwCompanyModel,
    StwContactModel,
    StwEngagementModel,
    StwEventModel,
    StwObjectiveModel,
    StwTransitionModel,
)
from arp.storage.safe_path import safe_id

_LOCK = text("SELECT pg_advisory_xact_lock(hashtext('engagement:' || :id))")  # own keyspace, apart from publish/facts.py
_CORRESPONDENCE_TYPES = {t.value for t in CorrespondenceType}
_FIELD_NAMES = {"occurred_at": "date"}  # column -> pydantic field, where they differ for client input


def _ts(value: str | None, field: str = "timestamp") -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ClientInputError(f"{field} is not an ISO 8601 timestamp: {value!r}") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _row(model, obj: BaseModel, **extra):
    """ORM row from a pydantic object: fields matched to columns by name, `extra` wins, ISO strings parsed."""
    values = {"source": "app", **obj.model_dump(mode="json"), **extra}
    return model(
        **{
            c.key: _ts(values[c.key], _FIELD_NAMES.get(c.key, c.key)) if isinstance(c.type, DateTime) else values[c.key]
            for c in model.__table__.columns
            if c.key in values
        }
    )


def _cols(row, **renames: str) -> dict:
    """Column values of `row`, NULLs dropped (the pydantic default applies), timestamps as UTC ISO strings;
    `renames` maps field name -> column name, applied in order."""
    out = {}
    for c in row.__table__.columns:
        value = getattr(row, c.key)
        if value is not None:
            out[c.key] = value.astimezone(UTC).isoformat() if isinstance(value, datetime) else value
    for field, column in renames.items():
        if column in out:
            out[field] = out.pop(column)
    return out


def _activity_type(entry: CorrespondenceEntry) -> str:
    # One column holds both fields: the VOICE activity_type when set, else the correspondence type.
    return (entry.activity_type or entry.type).value


def _entry(row: StwActivityModel) -> CorrespondenceEntry:
    values = _cols(row, entry_id="activity_id", date="occurred_at")
    kind = values.pop("activity_type", CorrespondenceType.OTHER.value)
    if kind in _CORRESPONDENCE_TYPES:
        values["type"] = kind
    else:
        values |= {"type": CorrespondenceType.OTHER, "activity_type": kind}
    return CorrespondenceEntry.model_validate(values)


class PostgresEngagementStore:
    """Drop-in for EngagementStore (arp/storage/engagement_store.py) on the stw_* tables. Rows it writes
    carry source = 'app' (or the object's own source) and no external_id."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._local = threading.local()  # the transaction a lock() on this thread holds

    @contextmanager
    def _session(self) -> Iterator[Session]:
        held = getattr(self._local, "session", None)
        if held is not None:
            yield held
            return
        with transaction(self.dsn) as session:
            yield session

    @contextmanager
    def lock(self, company_id: str) -> Iterator[None]:
        """One write transaction holding a per-company advisory lock until commit. Re-entrant on the
        same thread: a nested lock() joins the open transaction."""
        safe_id(company_id, label="company_id")  # same 4xx as the file store for malformed ids
        with self._session() as session:
            session.execute(_LOCK, {"id": company_id})
            outer = getattr(self._local, "session", None) is None
            self._local.session = session
            try:
                yield
            finally:
                if outer:
                    self._local.session = None

    @property
    def _tx(self) -> Session:
        return self._local.session

    def _add(self, row) -> None:
        """Insert `row`; an id the client chose that already exists (in any company) is a client error."""
        mapper = inspect(type(row))
        key = mapper.primary_key_from_instance(row)
        if self._tx.get(type(row), key) is not None:
            raise ClientInputError(f"{mapper.primary_key[0].key} already exists: {key[0]!r}")
        self._tx.add(row)

    def _log_event(self, company_id: str, event_type: str, detail: dict) -> None:
        self._tx.add(StwEventModel(source="app", company_id=company_id, event_type=event_type, detail=detail, at=_ts(now_iso())))

    def _touch(self, company_id: str) -> None:
        self._tx.get(StwCompanyModel, company_id).updated_at = _ts(now_iso())

    def _read(self, session: Session, company_id: str) -> EngagementRecord | None:
        company = session.get(StwCompanyModel, company_id)
        if company is None:
            return None
        E = StwEngagementModel
        engagement_ids = select(E.engagement_id).where(E.company_id == company_id)

        def created(event_type: str, key: str, column):
            # contacts and objectives have no reliable timestamp: their creation event's id is the append order
            seq = select(func.min(StwEventModel.event_id)).where(
                StwEventModel.company_id == company_id,
                StwEventModel.event_type == event_type,
                StwEventModel.detail[key].astext == column,
            )
            return seq.scalar_subquery().asc().nulls_last()

        def children(model, order):
            grouped = defaultdict(list)
            for row in session.scalars(select(model).where(model.engagement_id.in_(engagement_ids)).order_by(*order)):
                grouped[row.engagement_id].append(row)
            return grouped

        Ob, A, C, T = StwObjectiveModel, StwActivityModel, StwCommitmentModel, StwTransitionModel
        objectives = children(Ob, [created("objective_added", "objective_id", Ob.objective_id), Ob.started_at, Ob.objective_id])
        activities = children(A, [A.occurred_at, A.activity_id])
        commitments = children(C, [C.made_at, C.commitment_id])
        transitions = children(T, [T.changed_at, T.transition_id])
        issues = []
        for row in session.scalars(select(E).where(E.company_id == company_id).order_by(E.started_at, E.engagement_id)):
            moves = transitions[row.engagement_id]
            issues.append(
                EngagementIssue.model_validate(
                    _cols(row, issue_id="engagement_id", opened_at="started_at", data_source="source", source="trigger_source")
                    | {
                        "objectives": [Objective.model_validate(_cols(o)) for o in objectives[row.engagement_id]],
                        "correspondence": [_entry(a) for a in activities[row.engagement_id]],
                        "commitments": [Commitment.model_validate(_cols(c)) for c in commitments[row.engagement_id]],
                        "milestone_history": [
                            MilestoneTransition.model_validate(_cols(t)) for t in moves if t.kind == "milestone"
                        ],
                        "escalation_history": [
                            EscalationTransition.model_validate(_cols(t)) for t in moves if t.kind == "escalation"
                        ],
                    }
                )
            )
        Ct = StwContactModel
        contacts = session.scalars(
            select(Ct)
            .where(Ct.company_id == company_id)
            .order_by(created("contact_added", "contact_id", Ct.contact_id), Ct.contact_id)
        )
        return EngagementRecord.model_validate(
            _cols(company) | {"contacts": [Contact.model_validate(_cols(c)) for c in contacts], "issues": issues}
        )

    def get(self, company_id: str) -> EngagementRecord | None:
        safe_id(company_id, label="company_id")
        with self._session() as session:
            return self._read(session, company_id)

    def get_or_create(self, company_id: str, name: str, sector: str | None = None) -> EngagementRecord:
        with self.lock(company_id):
            existing = self.get(company_id)
            if existing is not None:
                return existing
            record = EngagementRecord(company_id=company_id, name=name, sector=sector)
            self._add(_row(StwCompanyModel, record))
            self._log_event(company_id, "record_created", {})
            return self.get(company_id)

    def list_all(self) -> list[EngagementRecord]:
        with self._session() as session:
            ids = session.scalars(select(StwCompanyModel.company_id).order_by(StwCompanyModel.company_id.collate("C"))).all()
            return [self._read(session, company_id) for company_id in ids]

    def events(self, company_id: str) -> list[dict]:
        safe_id(company_id, label="company_id")
        with self._session() as session:
            rows = session.scalars(
                select(StwEventModel).where(StwEventModel.company_id == company_id).order_by(StwEventModel.event_id)
            )
            return [
                {"event_type": e.event_type, "at": e.at.astimezone(UTC).isoformat() if e.at else None, **(e.detail or {})}
                for e in rows
            ]

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

    def _issue_in(self, company_id: str, issue_id: str) -> EngagementIssue:
        return self._find_issue(self._get_or_raise(company_id), issue_id)

    def _write(self, company_id: str, event_type: str, detail: dict) -> EngagementRecord:
        self._touch(company_id)
        self._log_event(company_id, event_type, detail)
        return self.get(company_id)

    def add_contact(self, company_id: str, contact: Contact) -> EngagementRecord:
        with self.lock(company_id):
            self._get_or_raise(company_id)
            self._add(_row(StwContactModel, contact, company_id=company_id))
            return self._write(company_id, "contact_added", {"contact_id": contact.contact_id, "name": contact.name})

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
        with self.lock(company_id):
            self.get_or_create(company_id, name, sector)
            issue = EngagementIssue(theme=theme, severity=severity, source=source, source_detail=source_detail, tags=[theme])
            self._add(
                _row(
                    StwEngagementModel,
                    issue,
                    engagement_id=issue.issue_id,
                    company_id=company_id,
                    started_at=issue.opened_at,
                    trigger_source=source.value,
                    source=issue.data_source,
                )
            )
            record = self._write(company_id, "issue_opened", {"issue_id": issue.issue_id, "theme": theme, "source": source.value})
            return record, issue

    def open_issues_for_theme(self, company_id: str, theme: str) -> list[EngagementIssue]:
        record = self.get(company_id)
        if record is None:
            return []
        return [i for i in record.issues if i.theme == theme and i.status not in (IssueStatus.RESOLVED, IssueStatus.CLOSED)]

    def set_issue_status(self, company_id: str, issue_id: str, status: IssueStatus) -> EngagementRecord:
        with self.lock(company_id):
            if self._issue_in(company_id, issue_id).status == status:
                return self.get(company_id)
            self._tx.get(StwEngagementModel, issue_id).status = status.value
            return self._write(company_id, "issue_status_changed", {"issue_id": issue_id, "status": status.value})

    def add_correspondence(self, company_id: str, issue_id: str, entry: CorrespondenceEntry) -> EngagementRecord:
        with self.lock(company_id):
            self._issue_in(company_id, issue_id)
            self._add(
                _row(
                    StwActivityModel,
                    entry,
                    activity_id=entry.entry_id,
                    engagement_id=issue_id,
                    occurred_at=entry.date,
                    activity_type=_activity_type(entry),
                )
            )
            return self._write(
                company_id, "correspondence_added", {"issue_id": issue_id, "entry_id": entry.entry_id, "type": entry.type.value}
            )

    def add_commitment(self, company_id: str, issue_id: str, commitment: Commitment) -> EngagementRecord:
        with self.lock(company_id):
            self._issue_in(company_id, issue_id)
            self._add(_row(StwCommitmentModel, commitment, engagement_id=issue_id))
            return self._write(company_id, "commitment_added", {"issue_id": issue_id, "commitment_id": commitment.commitment_id})

    def update_commitment_status(
        self, company_id: str, issue_id: str, commitment_id: str, status: CommitmentStatus, validated_by: str | None = None
    ) -> EngagementRecord:
        with self.lock(company_id):
            issue = self._issue_in(company_id, issue_id)
            if not any(c.commitment_id == commitment_id for c in issue.commitments):
                raise ValueError(f"Unknown commitment_id: {commitment_id}")
            row = self._tx.get(StwCommitmentModel, commitment_id)
            row.status, row.validated_by, row.validated_at = status.value, validated_by, _ts(now_iso())
            return self._write(
                company_id,
                "commitment_status_changed",
                {"issue_id": issue_id, "commitment_id": commitment_id, "status": status.value},
            )

    def _add_transition(self, issue_id: str, kind: str, transition: BaseModel) -> None:
        self._add(_row(StwTransitionModel, transition, transition_id=new_id("trn"), engagement_id=issue_id, kind=kind))

    def set_milestone_stage(self, company_id: str, issue_id: str, stage: MilestoneStage, reason: str = "") -> EngagementRecord:
        with self.lock(company_id):
            self._issue_in(company_id, issue_id)
            self._add_transition(issue_id, "milestone", MilestoneTransition(stage=stage, reason=reason))
            self._tx.get(StwEngagementModel, issue_id).milestone_stage = stage.value
            return self._write(company_id, "milestone_changed", {"issue_id": issue_id, "stage": stage.value, "reason": reason})

    def set_escalation_stage(
        self, company_id: str, issue_id: str, stage: EscalationStage, decided_by: str, reason: str = ""
    ) -> EngagementRecord:
        """Human checkpoint, as in EngagementStore.set_escalation_stage: only called with a `decided_by`."""
        with self.lock(company_id):
            self._issue_in(company_id, issue_id)
            self._add_transition(issue_id, "escalation", EscalationTransition(stage=stage, decided_by=decided_by, reason=reason))
            self._tx.get(StwEngagementModel, issue_id).escalation_stage = stage.value
            return self._write(
                company_id,
                "escalation_changed",
                {"issue_id": issue_id, "stage": stage.value, "decided_by": decided_by, "reason": reason},
            )

    def add_objective(self, company_id: str, issue_id: str, objective: Objective) -> EngagementRecord:
        with self.lock(company_id):
            self._issue_in(company_id, issue_id)
            self._add(_row(StwObjectiveModel, objective, engagement_id=issue_id))
            return self._write(company_id, "objective_added", {"issue_id": issue_id, "objective_id": objective.objective_id})

    def update_objective(self, company_id: str, issue_id: str, objective_id: str, **fields) -> EngagementRecord:
        unknown = set(fields) - set(Objective.model_fields) | ({"objective_id"} & set(fields))
        if unknown:
            raise ValueError(f"Cannot update objective field(s): {sorted(unknown)}")
        with self.lock(company_id):
            current = next((o for o in self._issue_in(company_id, issue_id).objectives if o.objective_id == objective_id), None)
            if current is None:
                raise ValueError(f"Unknown objective_id: {objective_id}")
            updated = Objective.model_validate({**current.model_dump(), **fields})
            changed = sorted(k for k in fields if getattr(updated, k) != getattr(current, k))
            if not changed:
                return self.get(company_id)
            new_row = _row(StwObjectiveModel, updated, engagement_id=issue_id)
            row = self._tx.get(StwObjectiveModel, objective_id)
            for key in changed:
                setattr(row, key, getattr(new_row, key))
            return self._write(
                company_id, "objective_updated", {"issue_id": issue_id, "objective_id": objective_id, "changed": changed}
            )

    def list_objectives(self, company_id: str, issue_id: str) -> list[Objective]:
        return self._issue_in(company_id, issue_id).objectives
