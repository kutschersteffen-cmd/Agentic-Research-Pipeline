"""Insert-only field observations with their citations, and the one function that maintains the
current-fact table (spec §2.5, §2.7, §3.2). `decide` is the §2.7 rule table; `record` and
`apply_decision` are its only writers."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from arp.db.fields import ensure_extracted_field
from arp.db.models import (
    CitationRole,
    CompanyFact,
    DecisionKind,
    Document,
    FactStatus,
    Field,
    FieldDefinition,
    FieldKind,
    FieldObservation,
    ReviewItem,
    ReviewItemObservation,
    Route,
    Run,
    RunError,
    SourceKind,
    ValueCitation,
    ValueState,
)

logger = logging.getLogger(__name__)

FactAction = Literal["insert", "supersede", "noop", "keep"]


@dataclass(kw_only=True)
class CitationIn:
    doc_id: str
    role: CitationRole = CitationRole.PRIMARY
    content_key: str | None = None
    page: int | None = None
    sheet: str | None = None
    location: str | None = None
    quote: str | None = None
    span_text: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    table_ref: dict | None = None
    passage_id: str | None = None
    grounded: bool = False
    match_method: str | None = None
    match_score: float | None = None


@dataclass(kw_only=True)
class ObservationIn:
    company_id: UUID
    field_id: str
    field_version: int
    source_kind: SourceKind
    period_end: date | None
    basis: str = ""
    value: Any
    value_state: ValueState
    unit: str | None = None
    canonical_value: float | None = None
    canonical_unit: str | None = None
    scale_applied: float | None = None
    fx_rate: float | None = None
    confidence: float | None = None
    checks: list | dict | None = None
    route: Route | None = None
    method: str | None = None
    period_start: date | None = None
    run_id: str | None = None
    source_id: int | None = None
    load_id: int | None = None
    citations: list[CitationIn] = field(default_factory=list)
    conflicting_sources: bool = False
    trial: bool = False
    held: bool = False


def _same(a, b) -> bool:
    from arp.orchestration.review_queue import same_value  # review_queue -> RunStore -> this module

    if isinstance(a, dict | list) or isinstance(b, dict | list):
        return a == b
    return same_value(a, b)


_ACCEPTED = {FactStatus.AUTO_ACCEPTED, FactStatus.APPROVED, FactStatus.EDITED}


def decide(current: CompanyFact | None, value, status: FactStatus, value_state: ValueState) -> FactAction:
    """Spec §2.7: a miss never removes a fact, a pending value never displaces one, a held value
    displaces only a pending or held one, an accepted different value or status supersedes it."""
    if value_state == ValueState.NOT_FOUND:
        return "noop" if current is None else "keep"
    if current is None:
        return "insert"
    if _same(current.value, value) and current.status == status:
        return "noop"
    if status == FactStatus.PENDING_REVIEW:
        return "keep"
    if status == FactStatus.HELD and current.status in _ACCEPTED:
        return "keep"  # values from another entity's documents never displace an accepted fact
    return "supersede"


def _status(o: ObservationIn) -> FactStatus:
    if o.held or o.route == Route.HOLD:
        return FactStatus.HELD
    if o.route == Route.REVIEW:
        return FactStatus.PENDING_REVIEW
    return FactStatus.AUTO_ACCEPTED


def _numeric(v) -> Decimal | None:
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
        return None
    return Decimal(repr(v))


def _current(session: Session, obs: FieldObservation) -> CompanyFact | None:
    return session.scalar(
        select(CompanyFact)
        .where(
            CompanyFact.company_id == obs.company_id, CompanyFact.field_id == obs.field_id,
            CompanyFact.period_end.is_not_distinct_from(obs.period_end), CompanyFact.basis == obs.basis,
            CompanyFact.valid_to.is_(None),
        )
        .with_for_update()
    )


def _write_fact(
    session: Session, obs: FieldObservation, *, value, status: FactStatus, value_state: ValueState,
    canonical_value, canonical_unit, decision_id: int | None = None, conflicting: bool = False,
    at: datetime | None = None,
) -> None:
    """Applies `decide` to the key's current fact under a row lock. A concurrent first insert for
    the same key trips `uq_company_facts_current`; the savepoint is rolled back and the lookup
    retried once, which then sees the other writer's row. One clock_timestamp() closes the old
    version and opens the new one, so versions never overlap or leave a gap. `at` (the importer's
    replay) dates the change instead, never before the current version opened."""
    for attempt in (1, 2):
        try:
            with session.begin_nested():
                current = _current(session, obs)
                if decide(current, value, status, value_state) in ("noop", "keep"):
                    return
                ts = _at(session, at, current)
                if current is not None:  # closed first: the partial unique index allows one open row
                    current.valid_to = ts
                    session.flush()
                new = CompanyFact(
                    company_id=obs.company_id, field_id=obs.field_id, period_end=obs.period_end, basis=obs.basis,
                    value=value, canonical_value=canonical_value, canonical_unit=canonical_unit, status=status,
                    observation_id=obs.id, decision_id=decision_id, conflicting_sources=conflicting, valid_from=ts,
                )
                session.add(new)
                session.flush()
                if current is not None:
                    current.superseded_by = new.id
                    session.flush()
            return
        except IntegrityError as exc:
            if attempt == 2 or "uq_company_facts_current" not in str(exc.orig):
                raise


def _ensure_fields(session: Session, observations: list[ObservationIn]) -> None:
    """Registers missing fields as kind=extracted with a minimal definition. ON CONFLICT first, so
    two companies' transactions registering one new field do not collide; ensure_extracted_field
    then refuses a retired or non-extracted field."""
    for field_id, version in sorted({(o.field_id, o.field_version) for o in observations}):
        if session.get(FieldDefinition, (field_id, version)) is None:
            session.execute(insert(Field).values(field_id=field_id, kind=FieldKind.EXTRACTED).on_conflict_do_nothing())
            session.execute(insert(FieldDefinition).values(
                field_id=field_id, version=version, name=field_id, data_type="text", definition={}
            ).on_conflict_do_nothing())
            ensure_extracted_field(session, field_id, session.get(FieldDefinition, (field_id, version)))


_NUMERIC_TYPES = {"number", "currency_amount", "percentage"}


def _fits(data_type: str, value) -> bool:
    """Whether a value matches its field's registered data type; enum, text and dates are unchecked."""
    if value is None:
        return True
    if data_type == "boolean":
        return isinstance(value, bool)
    if data_type in _NUMERIC_TYPES:
        if isinstance(value, bool):
            return False
        if isinstance(value, int | float):
            return True
        try:
            float(str(value).replace(",", ""))
            return True
        except ValueError:
            return False
    return True


def _run_error(session: Session, o: ObservationIn, error: dict) -> None:
    if o.run_id is not None:
        session.add(RunError(run_id=o.run_id, company_id=o.company_id, error=error))


def fits(session: Session, observations: list[ObservationIn]) -> list[bool]:
    """Whether each value fits its field's registered data type (what `record` keeps)."""
    types = {
        (d.field_id, d.version): d.data_type
        for d in session.scalars(select(FieldDefinition).where(
            tuple_(FieldDefinition.field_id, FieldDefinition.version).in_({(o.field_id, o.field_version) for o in observations})
        ))
    } if observations else {}
    return [_fits(types.get((o.field_id, o.field_version), ""), o.value) for o in observations]


def apply_observation(session: Session, row: FieldObservation, o: ObservationIn, *, at: datetime | None = None) -> None:
    """The current-fact update for one stored observation (`row`, recorded from `o`); trial ones make none.
    `at` dates the change (default: now)."""
    if not o.trial:
        _write_fact(
            session, row, value=row.value, status=_status(o), value_state=o.value_state,
            canonical_value=row.canonical_value, canonical_unit=o.canonical_unit, conflicting=o.conflicting_sources, at=at,
        )


def record(session: Session, observations: list[ObservationIn], *, apply_facts: bool = True) -> list[int | None]:
    """Inserts the observations and their citations, then (unless `apply_facts` is False) updates the
    current facts of every non-trial observation. A value that does not fit its field's data type is
    left out (None in the result) and a citation to an unregistered document dropped; each is reported
    to the observation run's run_errors. Returns the observation ids, aligned with `observations`."""
    from arp.db.runs import _jsonb_safe  # runs imports this module

    if not observations:
        return []
    _ensure_fields(session, observations)
    ok = fits(session, observations)
    cited = {c.doc_id for o in observations for c in o.citations}
    known = set(session.scalars(select(Document.doc_id).where(Document.doc_id.in_(cited)))) if cited else set()
    ids: list[int | None] = []
    for o, fit in zip(observations, ok, strict=True):
        if not fit:
            _run_error(session, o, _jsonb_safe({"kind": "invalid_value", "field_id": o.field_id, "raw": o.value}))
            ids.append(None)
            continue
        row = FieldObservation(
            company_id=o.company_id, field_id=o.field_id, field_version=o.field_version, source_kind=o.source_kind,
            run_id=o.run_id, source_id=o.source_id, load_id=o.load_id, period_start=o.period_start,
            period_end=o.period_end, basis=o.basis, value=_jsonb_safe(o.value), value_state=o.value_state,
            unit=o.unit, canonical_value=_numeric(o.canonical_value), canonical_unit=o.canonical_unit,
            scale_applied=o.scale_applied, fx_rate=o.fx_rate, confidence=o.confidence, checks=_jsonb_safe(o.checks),
            route=o.route, method=o.method,
        )
        session.add(row)
        session.flush()
        ids.append(row.id)
        for c in o.citations:
            if c.doc_id not in known:
                logger.warning("citation to unregistered document %s dropped (field %s)", c.doc_id, o.field_id)
                _run_error(session, o, {"kind": "unregistered_citation", "doc_id": c.doc_id})
                continue
            session.add(ValueCitation(observation_id=row.id, **{**_jsonb_safe(vars(c)), "role": c.role}))
        if apply_facts:
            apply_observation(session, row, o)
    session.flush()
    return ids


_DECIDED = {DecisionKind.APPROVE: FactStatus.APPROVED, DecisionKind.EDIT: FactStatus.EDITED,
            DecisionKind.CORRECT: FactStatus.EDITED, DecisionKind.HOLD: FactStatus.HELD}


_SKIP = object()


def queue_item(
    session: Session, run_id: str, item_key: str, payload: dict, *, company_id, observation_id: int | None, queued_at,
) -> int:
    """Queues a review item (re-queueing a key replaces its payload) and links it to the observations
    it decides: a value item to its observation, a whole-record item (no observation, keyed by the
    company id) to every observation of its run and company routed to review. Returns the item id."""
    stmt = insert(ReviewItem).values(
        run_id=run_id, item_key=item_key, company_id=company_id, observation_id=observation_id, payload=payload,
        queued_at=queued_at,
    )
    item = session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_review_items_key",
            set_={
                "payload": stmt.excluded.payload,
                "company_id": stmt.excluded.company_id,
                # a re-queue without a link (queue_for_review) keeps the one the item has
                "observation_id": func.coalesce(stmt.excluded.observation_id, ReviewItem.observation_id),
            },
        ).returning(ReviewItem.id, ReviewItem.observation_id, ReviewItem.company_id, ReviewItem.payload)
    ).one()
    if item.observation_id is not None:
        linked = [item.observation_id]
    elif item.company_id is not None and item_key == item.payload.get("company_id"):
        linked = session.scalars(select(FieldObservation.id).where(
            FieldObservation.run_id == run_id, FieldObservation.company_id == item.company_id,
            FieldObservation.route == Route.REVIEW,
        )).all()
    else:
        linked = []
    if linked:
        session.execute(insert(ReviewItemObservation).values(
            [{"review_item_id": item.id, "observation_id": o} for o in linked]
        ).on_conflict_do_nothing())
    return item.id


def _edited(obs: FieldObservation, edit, *, whole_record: bool):
    """The value an edit gives this observation, or _SKIP. Vote edits carry `vote`
    (voting/pipeline._human_decision_from_review_row); theme edits (the generic override box,
    `{"value": ...}`) replace the verdict; extraction edits carry `value`. A whole-record edit
    sets only the fields it names by field_id."""
    if not isinstance(edit, dict):
        edit = {"value": edit}
    if whole_record:
        return edit.get(obs.field_id, _SKIP)
    if obs.field_id.startswith("vote:"):
        return edit.get("vote", edit.get("value", obs.value))
    if obs.field_id.startswith("theme:"):
        base = obs.value if isinstance(obs.value, dict) else {}
        verdict = edit.get("verdict", edit.get("value", base.get("verdict")))
        return {**base, "verdict": verdict, "exposure_estimate": edit.get("exposure_estimate", base.get("exposure_estimate"))}
    return edit.get("value", obs.value)


def _at(session: Session, at: datetime | None, current: CompanyFact | None) -> datetime:
    """When a fact change happens: `at`, but not before the current version opened; None is now."""
    if at is None:
        return session.scalar(select(func.clock_timestamp()))
    return max(at, current.valid_from) if current is not None else at


def _reject(session: Session, obs: FieldObservation, at: datetime | None = None) -> None:
    """A rejected value that is the key's current pending fact stops being current; no other
    version takes its place."""
    with session.begin_nested():
        current = _current(session, obs)
        if current is not None and current.observation_id == obs.id and current.status == FactStatus.PENDING_REVIEW:
            current.valid_to = _at(session, at, current)
            session.flush()


def apply_decision(
    session: Session, review_item_id: int, decision: DecisionKind, edited_value: Any | None, decision_id: int,
    *, at: datetime | None = None,
) -> None:
    """A final review decision on the observations its item is linked to (`queue_item`): the item's
    observation, or for a whole-record item every observation of its run and company routed to review.
    approve/edit/correct/hold set the fact; reject retires a pending fact the rejected
    observation made current; escalate changes nothing. Trial runs never make facts. `at` dates the
    change (default: now)."""
    item = session.get(ReviewItem, review_item_id)
    if item is None or decision == DecisionKind.ESCALATE:
        return
    run = session.get(Run, item.run_id)
    if run is not None and (run.params or {}).get("trial"):
        return
    whole_record = item.observation_id is None
    observations = session.scalars(
        select(FieldObservation).join(ReviewItemObservation, ReviewItemObservation.observation_id == FieldObservation.id)
        .where(ReviewItemObservation.review_item_id == item.id).order_by(FieldObservation.id)
    ).all()
    status = _DECIDED.get(decision)
    for obs in observations:
        if decision == DecisionKind.REJECT:
            _reject(session, obs, at)
            continue
        value, state = obs.value, obs.value_state
        canonical_value, canonical_unit = obs.canonical_value, obs.canonical_unit
        if status == FactStatus.EDITED and edited_value is not None:
            value = _edited(obs, edited_value, whole_record=whole_record)
            if value is _SKIP:
                continue
            edit = edited_value if isinstance(edited_value, dict) else {}
            state = ValueState.NOT_FOUND if value is None else ValueState.FOUND
            canonical_value, canonical_unit = _numeric(edit.get("canonical_value")), edit.get("canonical_unit")
        _write_fact(
            session, obs, value=value, status=status, value_state=state, canonical_value=canonical_value,
            canonical_unit=canonical_unit, decision_id=decision_id, at=at,
        )
