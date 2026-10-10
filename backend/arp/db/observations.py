"""Insert-only field observations with their citations, and the one function that maintains the
current-fact table (spec §2.5, §2.7, §3.2). `decide` is the §2.7 rule table; `record` and
`apply_decision` are its only writers."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select
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
    Route,
    Run,
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


def decide(current: CompanyFact | None, value, status: FactStatus, value_state: ValueState) -> FactAction:
    """Spec §2.7: a miss never removes a fact, a pending value never displaces one, an accepted
    (or held) different value or status supersedes it."""
    if value_state == ValueState.NOT_FOUND:
        return "noop" if current is None else "keep"
    if current is None:
        return "insert"
    if _same(current.value, value) and current.status == status:
        return "noop"
    if status == FactStatus.PENDING_REVIEW:
        return "keep"
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


def _write_fact(
    session: Session, obs: FieldObservation, *, value, status: FactStatus, value_state: ValueState,
    canonical_value, canonical_unit, decision_id: int | None = None, conflicting: bool = False,
) -> None:
    """Applies `decide` to the key's current fact under a row lock. A concurrent first insert for
    the same key trips `uq_company_facts_current`; the savepoint is rolled back and the lookup
    retried once, which then sees the other writer's row."""
    for attempt in (1, 2):
        try:
            with session.begin_nested():
                current = session.scalar(
                    select(CompanyFact)
                    .where(
                        CompanyFact.company_id == obs.company_id, CompanyFact.field_id == obs.field_id,
                        CompanyFact.period_end.is_not_distinct_from(obs.period_end), CompanyFact.basis == obs.basis,
                        CompanyFact.valid_to.is_(None),
                    )
                    .with_for_update()
                )
                if decide(current, value, status, value_state) in ("noop", "keep"):
                    return
                if current is not None:  # closed first: the partial unique index allows one open row
                    current.valid_to = func.now()
                    session.flush()
                new = CompanyFact(
                    company_id=obs.company_id, field_id=obs.field_id, period_end=obs.period_end, basis=obs.basis,
                    value=value, canonical_value=canonical_value, canonical_unit=canonical_unit, status=status,
                    observation_id=obs.id, decision_id=decision_id, conflicting_sources=conflicting,
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


def record(session: Session, observations: list[ObservationIn]) -> list[int]:
    """Inserts the observations and their citations (citations to an unregistered document are
    dropped and logged), then updates the current facts of every non-trial observation.
    Returns the observation ids, in order."""
    from arp.db.runs import _jsonb_safe  # runs imports this module

    if not observations:
        return []
    _ensure_fields(session, observations)
    cited = {c.doc_id for o in observations for c in o.citations}
    known = set(session.scalars(select(Document.doc_id).where(Document.doc_id.in_(cited)))) if cited else set()
    ids = []
    for o in observations:
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
                continue
            session.add(ValueCitation(observation_id=row.id, **{**_jsonb_safe(vars(c)), "role": c.role}))
        if not o.trial:
            _write_fact(
                session, row, value=row.value, status=_status(o), value_state=o.value_state,
                canonical_value=row.canonical_value, canonical_unit=o.canonical_unit, conflicting=o.conflicting_sources,
            )
    session.flush()
    return ids


_DECIDED = {DecisionKind.APPROVE: FactStatus.APPROVED, DecisionKind.EDIT: FactStatus.EDITED,
            DecisionKind.CORRECT: FactStatus.EDITED, DecisionKind.HOLD: FactStatus.HELD}


def apply_decision(
    session: Session, review_item_id: int, decision: DecisionKind, edited_value: Any | None, decision_id: int
) -> None:
    """A final review decision on an item's observation: approve/edit/correct/hold set the fact;
    reject and escalate leave the current fact as it is. Trial-run observations never make facts."""
    status = _DECIDED.get(decision)
    item = session.get(ReviewItem, review_item_id)
    if status is None or item is None or item.observation_id is None:
        return
    obs = session.get(FieldObservation, item.observation_id)
    run = session.get(Run, obs.run_id) if obs.run_id else None
    if run is not None and (run.params or {}).get("trial"):
        return
    value, state = obs.value, obs.value_state
    canonical_value, canonical_unit = obs.canonical_value, obs.canonical_unit
    if status == FactStatus.EDITED and edited_value is not None:
        edit = edited_value if isinstance(edited_value, dict) else {"value": edited_value}
        value = edit.get("value", edited_value)
        state = ValueState.NOT_FOUND if value is None else ValueState.FOUND
        canonical_value, canonical_unit = _numeric(edit.get("canonical_value")), edit.get("canonical_unit")
    _write_fact(
        session, obs, value=value, status=status, value_state=state, canonical_value=canonical_value,
        canonical_unit=canonical_unit, decision_id=decision_id,
    )
