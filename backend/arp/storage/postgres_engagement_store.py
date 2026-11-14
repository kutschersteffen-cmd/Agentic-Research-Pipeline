"""Postgres engagement store (spec "Store and callers"): the same public surface as the file-based
EngagementStore, on the stw_* tables, plus VOICE objectives. Every write that changes data adds one
stw_events row; a write that changes nothing adds none."""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime

from pydantic import BaseModel
from sqlalchemy import DateTime, func, inspect, select, text
from sqlalchemy.orm import Session

from arp.db.session import transaction
from arp.engagement.tracking_agent import log_commitment_verified
from arp.errors import ClientInputError
from arp.schemas.common import new_id, now_iso
from arp.schemas.engagement import (
    Commitment,
    CommitmentStatus,
    Contact,
    CorrespondenceEntry,
    EngagementIssue,
    EngagementRecord,
    EscalationStage,
    EscalationTransition,
    EvidenceSuggestion,
    IssueSeverity,
    IssueStatus,
    MilestoneStage,
    MilestoneTransition,
    Objective,
    TriggerSource,
    WatchTopic,
    evidence_text,
)
from arp.storage.postgres_models import (
    StwActivityModel,
    StwCommitmentModel,
    StwCompanyModel,
    StwContactModel,
    StwEngagementModel,
    StwEventModel,
    StwEvidenceSuggestionModel,
    StwObjectiveModel,
    StwTransitionModel,
    StwWatchTopicModel,
)
from arp.storage.safe_path import safe_id

_LOCK = text("SELECT pg_advisory_xact_lock(hashtext('engagement:' || :id))")  # own keyspace, apart from publish/facts.py
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


def _entry(row: StwActivityModel) -> CorrespondenceEntry:
    return CorrespondenceEntry.model_validate(_cols(row, entry_id="activity_id", date="occurred_at"))


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
        self,
        company_id: str,
        issue_id: str,
        commitment_id: str,
        status: CommitmentStatus,
        validated_by: str | None = None,
        evidence: str | None = None,
    ) -> EngagementRecord:
        with self.lock(company_id):
            issue = self._issue_in(company_id, issue_id)
            if not any(c.commitment_id == commitment_id for c in issue.commitments):
                raise ValueError(f"Unknown commitment_id: {commitment_id}")
            row = self._tx.get(StwCommitmentModel, commitment_id)
            row.status, row.validated_by, row.validated_at, row.evidence = status.value, validated_by, _ts(now_iso()), evidence
            return self._write(
                company_id,
                "commitment_status_changed",
                {"issue_id": issue_id, "commitment_id": commitment_id, "status": status.value},
            )

    def _add_transition(self, issue_id: str, kind: str, transition: BaseModel) -> None:
        self._add(_row(StwTransitionModel, transition, transition_id=new_id("trn"), engagement_id=issue_id, kind=kind))

    def set_milestone_stage(
        self, company_id: str, issue_id: str, stage: MilestoneStage, reason: str = "", forward_only: bool = False
    ) -> EngagementRecord:
        """`forward_only` leaves an issue that is already at or past `stage` where it is."""
        with self.lock(company_id):
            issue = self._issue_in(company_id, issue_id)
            order = list(MilestoneStage)
            if forward_only and order.index(issue.milestone_stage) >= order.index(stage):
                return self.get(company_id)
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

    # --- Watch list (spec stewardship-commitment-loop) ---------------------------------------------
    # Raises WatchError(status, detail) with the spec's API messages, so every route words errors alike.

    def _engagement(self, company_id: str, issue_id: str) -> StwEngagementModel:
        row = self._tx.get(StwEngagementModel, issue_id)
        if row is None or row.company_id != company_id:
            raise WatchError(404, "Unknown engagement")
        return row

    def _item(self, issue_id: str, item_kind: str, item_id: str):
        model, missing = _ITEMS[item_kind]
        row = self._tx.get(model, item_id)
        if row is None or row.engagement_id != issue_id:
            raise WatchError(404, missing)
        return row

    def _log(self, company_id: str, event_type: str, detail: dict) -> None:
        self._touch(company_id)
        self._log_event(company_id, event_type, detail)

    def set_proof_statement(self, company_id: str, issue_id: str, item_kind: str, item_id: str, proof_statement: str) -> BaseModel:
        with self.lock(company_id):
            self._engagement(company_id, issue_id)
            row = self._item(issue_id, item_kind, item_id)
            if row.proof_statement != proof_statement:
                row.proof_statement = proof_statement
                self._log(company_id, "proof_statement_set", {"issue_id": issue_id, "item_kind": item_kind, "item_id": item_id})
            return _ITEM_OUT[item_kind].model_validate(_cols(row))

    def record_objective_result(
        self, company_id: str, issue_id: str, objective_id: str, result: str, influence_level: str | None, outcome: str
    ) -> Objective:
        with self.lock(company_id):
            self._engagement(company_id, issue_id)
            row = self._item(issue_id, "objective", objective_id)
            if row.status not in _OPEN_OBJECTIVE:
                raise WatchError(409, "This objective is already closed.")
            row.result, row.influence_level, row.outcome, row.closed_at = result, influence_level, outcome, _ts(now_iso())
            row.status = "abandoned" if result == "abandoned" else "closed"
            self._log(company_id, "objective_result_recorded", {"issue_id": issue_id, "objective_id": objective_id, "result": result})
            return Objective.model_validate(_cols(row))

    def add_watch_topic(self, company_id: str, issue_id: str, topic: WatchTopic) -> WatchTopic:
        with self.lock(company_id):
            if self._engagement(company_id, issue_id).status not in _OPEN_ENGAGEMENT:
                raise WatchError(409, "Watch topics need an open engagement.")
            self._add(_row(StwWatchTopicModel, topic, engagement_id=issue_id))
            self._log(company_id, "watch_topic_added", {"issue_id": issue_id, "topic_id": topic.topic_id})
            return topic

    def list_watch_topics(self, company_id: str) -> list[WatchTopic]:
        W = StwWatchTopicModel
        with self._session() as session:
            rows = session.scalars(
                select(W)
                .join(StwEngagementModel, StwEngagementModel.engagement_id == W.engagement_id)
                .where(StwEngagementModel.company_id == company_id)
                .order_by(W.created_at.desc(), W.topic_id.desc())
            )
            return [WatchTopic.model_validate(_cols(r)) for r in rows]

    def _company_of(self, model, key: str, missing: str) -> str:
        """The company a topic or suggestion belongs to, read before taking that company's lock."""
        with self._session() as session:
            row = session.get(model, key)
            if row is None:
                raise WatchError(404, missing)
            return row.company_id if model is StwEvidenceSuggestionModel else session.get(StwEngagementModel, row.engagement_id).company_id

    def close_watch_topic(self, topic_id: str, closed_by: str) -> WatchTopic:
        company_id = self._company_of(StwWatchTopicModel, topic_id, "Unknown topic.")
        with self.lock(company_id):
            row = self._tx.get(StwWatchTopicModel, topic_id)
            if row.status == "closed":
                raise WatchError(409, "This topic is already closed.")
            row.status, row.closed_by, row.closed_at = "closed", closed_by, _ts(now_iso())
            self._log(company_id, "watch_topic_closed", {"issue_id": row.engagement_id, "topic_id": topic_id})
            return WatchTopic.model_validate(_cols(row))

    def list_suggestions(self, company_id: str, status: str) -> list[EvidenceSuggestion]:
        S = StwEvidenceSuggestionModel
        with self._session() as session:
            rows = session.scalars(
                select(S).where(S.company_id == company_id, S.status == status).order_by(S.created_at.desc(), S.suggestion_id.desc())
            )
            return [EvidenceSuggestion.model_validate(_cols(r)) for r in rows]

    def _decide(self, row: StwEvidenceSuggestionModel, status: str, user: str, **fields) -> EvidenceSuggestion:
        if row.status != "pending":
            raise WatchError(409, f"Suggestion already {row.status}.")
        row.status, row.decided_by, row.decided_at = status, user, _ts(now_iso())
        for key, value in fields.items():
            setattr(row, key, value)
        self._log(row.company_id, f"evidence_suggestion_{status}", {"suggestion_id": row.suggestion_id, "item_id": row.item_id})
        return EvidenceSuggestion.model_validate(_cols(row))

    def reject_suggestion(self, suggestion_id: str, user: str, reason: str) -> EvidenceSuggestion:
        company_id = self._company_of(StwEvidenceSuggestionModel, suggestion_id, "Unknown suggestion.")
        with self.lock(company_id):
            return self._decide(self._tx.get(StwEvidenceSuggestionModel, suggestion_id), "rejected", user, reject_reason=reason)

    def confirm_suggestion(self, suggestion_id: str, user: str, overrides: dict | None = None) -> EvidenceSuggestion:
        """Confirming is the person's decision: on a commitment it sets verified/missed as Verify does; on an
        objective or topic it records the evidence only; a new_commitment adds the commitment (spec "API")."""
        company_id = self._company_of(StwEvidenceSuggestionModel, suggestion_id, "Unknown suggestion.")
        with self.lock(company_id):
            row = self._tx.get(StwEvidenceSuggestionModel, suggestion_id)
            if row.status != "pending":
                raise WatchError(409, f"Suggestion already {row.status}.")
            if row.kind == "new_commitment":
                return self._decide(row, "confirmed", user, created_commitment_id=self._add_found_commitment(row, user, overrides or {}))
            item = self._tx.get(_ITEMS[row.item_kind][0], row.item_id)
            engagement = self._tx.get(StwEngagementModel, row.engagement_id)
            if item is None or item.status not in _OPEN_ITEM[row.item_kind] or engagement.status not in _OPEN_ENGAGEMENT:
                raise WatchError(409, "This item is no longer open.")
            if row.item_kind == "commitment":
                evidence = evidence_text(EvidenceSuggestion.model_validate(_cols(row)))
                if row.verdict == "found":
                    log_commitment_verified(self, company_id, row.engagement_id, row.item_id, user, evidence)
                else:
                    self.update_commitment_status(company_id, row.engagement_id, row.item_id, CommitmentStatus.MISSED, user, evidence)
            return self._decide(row, "confirmed", user)

    def _add_found_commitment(self, row: StwEvidenceSuggestionModel, user: str, overrides: dict) -> str:
        target_date = overrides.get("target_date") or row.target_date
        if not target_date:
            raise WatchError(422, "A due date is required to add a commitment.")
        if not is_iso_date(target_date):
            raise WatchError(422, "target_date must be an ISO date")
        activity = self._tx.get(StwActivityModel, row.activity_id)
        commitment = Commitment(
            text=overrides.get("text") or row.text,
            proof_statement=overrides.get("proof_statement") or row.proof_statement,
            target_date=target_date,
            recorded_by=user,
            **({"made_at": activity.occurred_at.astimezone(UTC).isoformat()} if activity.occurred_at else {}),
        )
        self.add_commitment(row.company_id, row.engagement_id, commitment)
        return commitment.commitment_id


class WatchError(Exception):
    """A watch-list request the store refuses: `status` is the HTTP status the API answers with."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status, self.detail = status, detail


def is_iso_date(value: str) -> bool:
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


_OPEN_ENGAGEMENT = ("open", "stalled")
_OPEN_OBJECTIVE = ("initiated", "in_progress")
_OPEN_ITEM = {"objective": _OPEN_OBJECTIVE, "commitment": ("open",), "topic": ("open",)}
_ITEMS = {
    "objective": (StwObjectiveModel, "Unknown objective."),
    "commitment": (StwCommitmentModel, "Unknown commitment."),
    "topic": (StwWatchTopicModel, "Unknown topic."),
}
_ITEM_OUT: dict[str, type[BaseModel]] = {"objective": Objective, "commitment": Commitment, "topic": WatchTopic}
