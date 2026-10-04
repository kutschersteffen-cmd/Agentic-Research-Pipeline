"""Published facts, releases and outbox events, plus the pure versioning
rule (E72), and the Postgres store. sqlalchemy is imported lazily; the tables live in
arp/storage/postgres_models.py."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from arp.orchestration.review_queue import same_value
from arp.schemas.common import Citation, new_id

FactKey = tuple[str, str, str, str]
FactState = Literal["approved", "edited", "auto_accepted"]
EventType = Literal["published", "restated", "withdrawn", "restored"]


def ts_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


class FactCandidate(BaseModel):
    issuer_key: str
    issuer_scheme: str
    field_id: str
    period_end: str
    basis: str = ""
    value: str | float | bool | None
    unit: str | None = None
    canonical_value: float | None = None
    canonical_unit: str | None = None
    state: FactState
    citation: Citation | None
    source_run_id: str
    observed_at: str
    item_key: str
    restated: bool = False
    restated_by_doc_id: str | None = None


class Fact(FactCandidate):
    fact_id: str = Field(default_factory=lambda: new_id("fact"))
    citation: Citation
    version: int = Field(ge=1)
    valid_from: str
    valid_to: str | None = None
    superseded_by: str | None = None
    reconfirmed_at: str | None = None
    release_id: str
    restored_from: str | None = None


def fact_key(x: Fact | FactCandidate) -> FactKey:
    return (x.issuer_key, x.field_id, x.period_end, x.basis)


def same_fact_value(a, b) -> bool:
    return same_value(a.value, b.value) and a.unit == b.unit and a.canonical_unit == b.canonical_unit


@dataclass(frozen=True)
class VersionPlan:
    kind: Literal["insert", "reconfirm", "older"]
    fact: Fact | None
    closes: Fact | None = None


def plan_version(current: Fact | None, cand: FactCandidate, *, release_id: str, now: str) -> VersionPlan:
    if current is not None and same_fact_value(current, cand):
        return VersionPlan("reconfirm", current.model_copy(update={"reconfirmed_at": now}))
    if current is not None and cand.observed_at < current.observed_at:
        return VersionPlan("older", None)
    new = Fact(
        **cand.model_dump(exclude={"citation"}),
        citation=cand.citation,
        version=1 if current is None else current.version + 1,
        valid_from=now,
        release_id=release_id,
    )
    if current is None:
        return VersionPlan("insert", new)
    closes = current.model_copy(update={"valid_to": now, "superseded_by": new.fact_id})
    return VersionPlan("insert", new, closes)


class Release(BaseModel):
    release_id: str = Field(default_factory=lambda: new_id("rel"))
    doc_id: str
    content_key: str
    storage_uri: str
    issuer_key: str
    issuer_scheme: str
    run_id: str
    published_at: str
    published_by: str
    published_by_role: str
    withdrawn_at: str | None = None
    withdrawal_reason: str | None = None
    withdrawn_by: str | None = None


def public_release(r: Release) -> dict:
    return r.model_dump(mode="json", exclude={"published_by", "withdrawn_by", "storage_uri"})


class FactEvent(BaseModel):
    event_id: int | None = None
    event_type: EventType
    fact_id: str
    issuer_key: str
    field_id: str
    period_end: str
    basis: str
    release_id: str
    at: str


EVENT_LOCK = 7600076  # advisory-lock key serialising outbox writes


class ConcurrentPublish(RuntimeError):
    """Another publish changed a fact first."""


SERIALIZATION_FAILURES = {"40P01", "40001"}  # deadlock_detected, serialization_failure


@contextmanager
def _concurrent_on_serialization_failure():
    from sqlalchemy.exc import OperationalError

    try:
        yield
    except OperationalError as exc:
        if getattr(exc.orig, "sqlstate", None) in SERIALIZATION_FAILURES:
            raise ConcurrentPublish(str(exc.orig)) from exc
        raise


def _fact(row) -> Fact:
    return Fact.model_validate({c.key: getattr(row, c.key) for c in row.__table__.columns})


def _release(row) -> Release:
    return Release.model_validate({c.key: getattr(row, c.key) for c in row.__table__.columns})


class PublishStore:
    """Postgres store for published facts, releases and the outbox (E72)."""

    def __init__(self, dsn: str):
        from arp.storage.postgres import get_engine

        self.engine = get_engine(dsn)

    def session(self):
        from sqlalchemy.orm import Session

        return Session(self.engine)

    def current(self, keys: Iterable[FactKey]) -> dict[FactKey, Fact]:
        from sqlalchemy import select, tuple_

        from arp.storage.postgres_models import PublishedFactModel as M

        keys = list(keys)
        if not keys:
            return {}
        cols = tuple_(M.issuer_key, M.field_id, M.period_end, M.basis)
        with self.session() as s:
            rows = s.scalars(select(M).where(cols.in_(keys), M.valid_to.is_(None)))
            return {fact_key(f): f for f in map(_fact, rows)}

    def versions(self, key: FactKey) -> list[Fact]:
        from sqlalchemy import select

        from arp.storage.postgres_models import PublishedFactModel as M

        issuer_key, field_id, period_end, basis = key
        q = select(M).where(
            M.issuer_key == issuer_key, M.field_id == field_id, M.period_end == period_end, M.basis == basis
        )
        with self.session() as s:
            return [_fact(r) for r in s.scalars(q.order_by(M.version))]

    def get_fact(self, fact_id: str) -> Fact | None:
        from arp.storage.postgres_models import PublishedFactModel as M

        with self.session() as s:
            row = s.get(M, fact_id)
            return _fact(row) if row else None

    def previous_version(self, fact_id: str) -> Fact | None:
        from sqlalchemy import select

        from arp.storage.postgres_models import PublishedFactModel as M

        with self.session() as s:
            row = s.scalars(select(M).where(M.superseded_by == fact_id)).first()
            return _fact(row) if row else None

    def _close(self, s, fact: Fact) -> None:
        from sqlalchemy import update

        from arp.storage.postgres_models import PublishedFactModel as M

        res = s.execute(
            update(M)
            .where(M.fact_id == fact.fact_id, M.valid_to.is_(None))
            .values(valid_to=fact.valid_to, superseded_by=fact.superseded_by)
        )
        if res.rowcount != 1:
            raise ConcurrentPublish(f"fact {fact.fact_id} was already closed")

    def _commit(self, s, events: list[FactEvent]) -> None:
        from sqlalchemy import func, select
        from sqlalchemy.exc import IntegrityError

        from arp.storage.postgres_models import FactEventModel

        # One global lock held to commit: event ids are then assigned in commit order, so a
        # consumer's `event_id` cursor can never skip an event that commits late.
        s.execute(select(func.pg_advisory_xact_lock(EVENT_LOCK)))
        s.add_all(FactEventModel(**e.model_dump(exclude={"event_id"})) for e in events)
        try:
            s.commit()
        except IntegrityError as exc:
            raise ConcurrentPublish(str(exc.orig)) from exc

    def save_release(self, release: Release | None, plans: list[VersionPlan], events: list[FactEvent]) -> None:
        from sqlalchemy import update
        from sqlalchemy.exc import IntegrityError

        from arp.storage.postgres_models import PublishedFactModel as M
        from arp.storage.postgres_models import ReleaseModel

        # Rows in key order, so two publishes over overlapping keys lock them in the same order.
        plans = sorted(plans, key=lambda p: fact_key(p.fact) if p.fact is not None else ("",) * 4)
        with _concurrent_on_serialization_failure(), self.session() as s:
            try:
                if release is not None:
                    s.add(ReleaseModel(**release.model_dump()))
                    s.flush()  # no relationship(): the fact's release FK needs this row first
                for p in plans:
                    if p.kind == "insert":
                        s.add(M(**p.fact.model_dump(mode="json")))
                        s.flush()  # the closing UPDATE's superseded_by FK needs the new row
                        if p.closes is not None:
                            self._close(s, p.closes)
                    elif p.kind == "reconfirm":
                        res = s.execute(
                            update(M)
                            .where(M.fact_id == p.fact.fact_id, M.valid_to.is_(None))
                            .values(reconfirmed_at=p.fact.reconfirmed_at)
                        )
                        if res.rowcount != 1:
                            raise ConcurrentPublish(f"fact {p.fact.fact_id} is no longer current")
            except IntegrityError as exc:
                raise ConcurrentPublish(str(exc.orig)) from exc
            self._commit(s, events)

    def get_release(self, release_id: str) -> Release | None:
        from arp.storage.postgres_models import ReleaseModel

        with self.session() as s:
            row = s.get(ReleaseModel, release_id)
            return _release(row) if row else None

    def list_releases(self, *, doc_id: str | None = None, run_id: str | None = None) -> list[Release]:
        from sqlalchemy import select

        from arp.storage.postgres_models import ReleaseModel as R

        q = select(R).order_by(R.published_at)
        if doc_id is not None:
            q = q.where(R.doc_id == doc_id)
        if run_id is not None:
            q = q.where(R.run_id == run_id)
        with self.session() as s:
            return [_release(r) for r in s.scalars(q)]

    def release_facts(self, release_id: str) -> list[Fact]:
        from sqlalchemy import select

        from arp.storage.postgres_models import PublishedFactModel as M

        with self.session() as s:
            return [_fact(r) for r in s.scalars(select(M).where(M.release_id == release_id).order_by(M.valid_from))]

    def save_withdrawal(
        self, release: Release, closes: list[Fact], restores: list[Fact], events: list[FactEvent]
    ) -> None:
        from sqlalchemy import func, select, update
        from sqlalchemy.exc import IntegrityError

        from arp.storage.postgres_models import PublishedFactModel as M
        from arp.storage.postgres_models import ReleaseModel as R

        closes, restores = sorted(closes, key=fact_key), sorted(restores, key=fact_key)
        with _concurrent_on_serialization_failure(), self.session() as s:
            try:
                # Serialise withdrawals per issuer, then re-check what was planned outside the lock.
                for issuer in sorted({release.issuer_key, *(f.issuer_key for f in closes + restores)}):
                    s.execute(select(func.pg_advisory_xact_lock(func.hashtext(issuer))))
                sources = {f.release_id for f in restores}
                if sources and s.scalar(select(func.count()).where(R.release_id.in_(sources), R.withdrawn_at.is_not(None))):
                    raise ConcurrentPublish("a restored value's release was withdrawn meanwhile")
                open_ids = set(s.scalars(select(M.fact_id).where(M.release_id == release.release_id, M.valid_to.is_(None))))
                if open_ids - {f.fact_id for f in closes}:
                    raise ConcurrentPublish(f"release {release.release_id} gained a current fact meanwhile")
                res = s.execute(
                    update(R)
                    .where(R.release_id == release.release_id, R.withdrawn_at.is_(None))
                    .values(
                        withdrawn_at=release.withdrawn_at,
                        withdrawal_reason=release.withdrawal_reason,
                        withdrawn_by=release.withdrawn_by,
                    )
                )
                if res.rowcount != 1:
                    raise ConcurrentPublish(f"release {release.release_id} was already withdrawn")
                s.add_all(M(**f.model_dump(mode="json")) for f in restores)
                s.flush()  # each close's superseded_by FK needs its restored copy
                for f in closes:
                    self._close(s, f)
            except IntegrityError as exc:
                raise ConcurrentPublish(str(exc.orig)) from exc
            self._commit(s, events)

    def lineage(self, fact_id: str) -> dict | None:
        from sqlalchemy import select

        from arp.storage.postgres_models import PublishedFactModel as M
        from arp.storage.postgres_models import ReleaseModel as R

        q = (
            select(M, R.doc_id, R.content_key, R.storage_uri)
            .join(R, R.release_id == M.release_id)
            .where(M.fact_id == fact_id)
        )
        with self.session() as s:
            row = s.execute(q).first()
        if row is None:
            return None
        fact = _fact(row[0]).model_dump(mode="json")
        return {
            "fact": fact,
            "citation": fact["citation"],
            "release_id": fact["release_id"],
            "doc_id": row.doc_id,
            "content_key": row.content_key,
            "storage_uri": row.storage_uri,
            "source_run_id": fact["source_run_id"],
            "item_key": fact["item_key"],
        }
