"""Provider data sources (spec §2.4, §2.5): each pull is a recorded load whose raw payload is kept in
object storage; its rows become provider observations on the provider's own fields
(`prov:<slug>:<code>`). Provider rows never create companies."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from arp.config import get_settings
from arp.db.companies import lookup, resolve
from arp.db.fields import FieldIdCollision, provider_field_id, register_provider_field
from arp.db.models import (
    DataSource,
    FieldDefinition,
    IdScheme,
    Licence,
    LoadStatus,
    ProviderMetricCode,
    SourceKind,
    SourceKindDS,
    SourceLoad,
    ValueState,
)
from arp.db.observations import ObservationIn, record


@dataclass
class LoadResult:
    load_id: int
    unchanged: bool


@dataclass
class ProviderRow:
    issuer_ids: list[tuple[IdScheme | str, str]]
    metric_code: str
    metric_name: str
    unit: str | None
    data_type: str
    period_end: date | None
    value: Any


@dataclass
class IngestReport:
    observations: int = 0
    unmatched_issuers: list[list[tuple[str, str]]] = field(default_factory=list)
    collisions: list[str] = field(default_factory=list)


def _blob_store():
    from arp.storage.document_blob_store import DocumentBlobStore, LocalBlobStore

    s = get_settings()
    if s.object_store_endpoint_url:
        return DocumentBlobStore(s.object_store_endpoint_url, s.object_store_access_key, s.object_store_secret_key, s.object_store_bucket)
    return LocalBlobStore(s.blob_store_dir)


def _payload_key(session: Session, load: SourceLoad) -> str:
    return f"provider-loads/{session.get(DataSource, load.source_id).slug}/{load.payload_sha}"


def ensure_source(
    session: Session, slug: str, *, name: str, kind: str, licence: Licence, id_scheme: IdScheme | str | None
) -> int:
    """The source's id; an existing slug is returned as is (slugs are immutable, never renamed)."""
    if not re.fullmatch(r"[a-z0-9_]+", slug):
        raise ValueError(f"invalid source slug {slug!r}")
    session.execute(insert(DataSource).values(
        slug=slug, name=name, kind=SourceKindDS(kind), licence=Licence(licence), id_scheme=str(id_scheme) if id_scheme else None,
    ).on_conflict_do_nothing(index_elements=["slug"]))
    return session.scalar(select(DataSource.source_id).where(DataSource.slug == slug))


def record_load(session: Session, source_id: int, payload: bytes, *, request: dict, as_of: date) -> LoadResult:
    """Stores the payload, then records the load. A payload this source already delivered is
    `unchanged` and adds no row."""
    sha = hashlib.sha256(payload).hexdigest()
    seen = session.scalar(select(SourceLoad.load_id).where(SourceLoad.source_id == source_id, SourceLoad.payload_sha == sha))
    if seen is not None:
        return LoadResult(seen, True)
    load = SourceLoad(source_id=source_id, as_of=as_of, request=request, payload_sha=sha, status=LoadStatus.FETCHED)
    load.payload_uri = _blob_store().put(_payload_key(session, load), payload)
    session.add(load)
    session.flush()
    return LoadResult(load.load_id, False)


def _company(session: Session, src: DataSource, ids: list[tuple[str, str]]):
    """Matches on the provider's own id and the other ids already known; only the provider's id is
    stored as a new alias (a provider's ISIN or LEI is not trusted enough to become one)."""
    own = [(s, v) for s, v in ids if s == src.id_scheme]
    known = [(s, v) for s, v in ids if s != src.id_scheme and lookup(session, s, v)]
    return resolve(session, own + known, name="", allow_create=False).company_id


def _ingest(session: Session, load: SourceLoad, rows: list[ProviderRow]) -> IngestReport:
    src = session.get(DataSource, load.source_id)
    report = IngestReport()
    first = {}
    for r in rows:
        first.setdefault(r.metric_code, r)
    field_of = dict(session.execute(select(ProviderMetricCode.provider_code, ProviderMetricCode.field_id).where(
        ProviderMetricCode.source_id == src.source_id, ProviderMetricCode.provider_code.in_(first)
    )).all())
    new: dict[str, list[str]] = defaultdict(list)
    for code in first:
        if code not in field_of:
            new[provider_field_id(src.slug, code)].append(code)
    for codes in new.values():
        if len(codes) > 1:  # both codes normalise to one id: neither is ingested
            report.collisions += codes
            continue
        r = first[codes[0]]
        try:
            field_of[r.metric_code] = register_provider_field(
                session, src.source_id, r.metric_code, name=r.metric_name, unit=r.unit, data_type=r.data_type
            )
        except FieldIdCollision:
            report.collisions.append(r.metric_code)
    versions = dict(session.execute(select(FieldDefinition.field_id, func.max(FieldDefinition.version)).where(
        FieldDefinition.field_id.in_(set(field_of.values()))
    ).group_by(FieldDefinition.field_id)).all())

    companies: dict[tuple, Any] = {}
    observations = []
    for r in rows:
        fid = field_of.get(r.metric_code)
        if fid is None:
            continue
        ids = tuple((str(s), v) for s, v in r.issuer_ids)
        if ids not in companies:
            companies[ids] = _company(session, src, list(ids))
            if companies[ids] is None:
                report.unmatched_issuers.append(list(ids))
        if companies[ids] is None:
            continue
        observations.append(ObservationIn(
            company_id=companies[ids], field_id=fid, field_version=versions[fid], source_kind=SourceKind.PROVIDER,
            source_id=src.source_id, load_id=load.load_id, period_end=r.period_end, value=r.value,
            value_state=ValueState.NOT_FOUND if r.value is None else ValueState.FOUND,
            unit=r.unit, canonical_value=r.value, canonical_unit=r.unit,
        ))
    report.observations = sum(i is not None for i in record(session, observations))
    return report


def _guarded(session: Session, load_id: int, make_rows: Callable[[], list[ProviderRow]]) -> IngestReport:
    """Runs the ingest in a savepoint; on failure the load is marked failed (in the caller's
    transaction) and the exception re-raised."""
    load = session.get(SourceLoad, load_id)
    try:
        with session.begin_nested():
            report = _ingest(session, load, make_rows())
    except Exception as exc:
        load.status, load.error = LoadStatus.FAILED, str(exc)
        session.flush()
        raise
    load.status, load.error = LoadStatus.INGESTED, None
    session.flush()
    return report


def ingest_rows(session: Session, load_id: int, rows: list[ProviderRow]) -> IngestReport:
    return _guarded(session, load_id, lambda: rows)


def reingest(session: Session, load_id: int, parse: Callable[[bytes], list[ProviderRow]]) -> IngestReport:
    """Re-parses the stored payload; the provider is not called again."""
    payload = _blob_store().get(_payload_key(session, session.get(SourceLoad, load_id)))
    return _guarded(session, load_id, lambda: parse(payload))
