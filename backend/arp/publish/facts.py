"""Published facts, releases and outbox events, plus the pure versioning
rule (E72). No sqlalchemy import here; the tables live in
arp/storage/postgres_models.py."""

from __future__ import annotations

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
    return r.model_dump(mode="json", exclude={"published_by", "withdrawn_by"})


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
