"""Read-only one-company view (spec §4.1): search, summary, facts as of a time, fact trail, and the
per-company run-result queries that replaced `api/company_results.py`."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import PurePath
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from arp.db import models as m
from arp.db.companies import lookup, normalise_identifier


class IdentifierOut(BaseModel):
    scheme: str
    value: str
    valid_from: date
    valid_to: date | None


class CompanySearchHit(BaseModel):
    id: UUID
    name: str
    country: str | None
    sector: str | None
    identifiers: list[IdentifierOut]


class HolderOut(BaseModel):
    holder_id: str
    kind: str
    as_of_date: str
    weight_pct: float | None = None


class CompanySummary(BaseModel):
    id: UUID
    name: str
    country: str | None
    sector: str | None
    isic_code: str | None
    fiscal_year_end: str | None
    regimes: list[str]
    identifiers: list[IdentifierOut]
    fact_counts: dict[str, int]
    open_review_items: int
    documents: int
    runs: int
    holders: list[HolderOut]
    holders_available: bool


class CompanyFactRow(BaseModel):
    fact_id: int
    field_id: str
    kind: m.FieldKind
    period_end: date | None
    basis: str
    value: Any
    canonical_value: float | None
    canonical_unit: str | None
    status: m.FactStatus
    source_kind: m.SourceKind
    source_label: str
    licence: m.Licence | None
    conflicting_sources: bool
    valid_from: datetime
    valid_to: datetime | None


class CitationOut(BaseModel):
    doc_id: str
    title: str
    page: int | None
    quote: str | None
    char_start: int | None
    char_end: int | None
    passage_id: str | None
    role: m.CitationRole
    grounded: bool
    # What the raw-file route /api/documents/{company_id}/{doc_type}/{filename}/raw needs, in the
    # registry's original case (the company's UNIVERSE identifier is stored normalised).
    company_id: str
    doc_type: str
    source_filename: str | None
    source_url: str | None


class LoadOut(BaseModel):
    source_name: str
    fetched_at: datetime
    payload_uri: str | None


class DecisionOut(BaseModel):
    decision: m.DecisionKind | None
    reviewer: str | None
    decided_at: datetime
    comment: str | None


class ObservationOut(BaseModel):
    id: int
    source_kind: m.SourceKind
    run_id: str | None
    value: Any
    value_state: m.ValueState
    unit: str | None
    confidence: float | None
    route: m.Route | None
    created_at: datetime


class FactVersion(BaseModel):
    fact_id: int
    status: m.FactStatus
    value: Any
    valid_from: datetime
    valid_to: datetime | None
    superseded_by: int | None
    observation: ObservationOut
    citations: list[CitationOut]
    load: LoadOut | None
    decisions: list[DecisionOut]


class FactTrail(BaseModel):
    fact_id: int
    company_id: UUID
    field_id: str
    period_end: date | None
    basis: str
    versions: list[FactVersion]


def _identifiers(session: Session, ids: list[UUID]) -> dict[UUID, list[IdentifierOut]]:
    out: dict[UUID, list[IdentifierOut]] = {i: [] for i in ids}
    rows = session.scalars(
        select(m.CompanyIdentifier)
        .where(m.CompanyIdentifier.company_id.in_(ids), m.CompanyIdentifier.valid_to.is_(None))
        .order_by(m.CompanyIdentifier.scheme, m.CompanyIdentifier.value)
    )
    for r in rows:
        out[r.company_id].append(IdentifierOut(scheme=r.scheme, value=r.value, valid_from=r.valid_from, valid_to=r.valid_to))
    return out


def resolve_ref(session: Session, ref: str) -> UUID | None:
    """A company UUID, or `<SCHEME>:<value>` (scheme case-insensitive, value normalised)."""
    ref = ref.strip()
    try:
        cid = UUID(ref)
    except ValueError:
        scheme, sep, value = ref.partition(":")
        scheme = scheme.strip().upper()
        return lookup(session, scheme, value.strip()) if sep and scheme and value.strip() else None
    merged = lookup(session, m.IdScheme.MERGED_INTO, str(cid))  # a merged-away id opens the company it went into
    return merged or (cid if session.get(m.Company, cid) is not None else None)


def search(session: Session, q: str, limit: int = 20) -> list[CompanySearchHit]:
    q = q.strip()
    query = select(m.Company).order_by(m.Company.name).limit(limit)
    if q:
        alias = select(m.CompanyIdentifier.company_id).where(
            m.CompanyIdentifier.valid_to.is_(None), m.CompanyIdentifier.value.ilike(f"%{normalise_identifier('', q)}%")
        )
        query = query.where(or_(m.Company.name.ilike(f"%{q}%"), m.Company.id.in_(alias)))
    companies = session.scalars(query).all()
    ids = _identifiers(session, [c.id for c in companies])
    return [CompanySearchHit(id=c.id, name=c.name, country=c.country, sector=c.sector, identifiers=ids[c.id]) for c in companies]


def _holders(store, company_id: UUID, identifiers: list[IdentifierOut], today: date) -> list[HolderOut]:
    """Each holder's latest snapshot on or before `today`, matched on any active identifier."""
    by_scheme = {(i.scheme, i.value) for i in identifiers}
    universe = {i.value for i in identifiers if i.scheme == "UNIVERSE"}

    def matches(h) -> bool:
        if h.isin and ("ISIN", normalise_identifier("ISIN", h.isin)) in by_scheme:
            return True
        if h.issuer_key:
            scheme = h.issuer_scheme or "LEI"
            if scheme == "INTERNAL":
                if h.issuer_key == str(company_id):
                    return True
            elif (scheme, normalise_identifier(scheme, h.issuer_key)) in by_scheme:
                return True
        sec = store.get_security(h.security_id)
        return bool(sec and sec.company_id and normalise_identifier("UNIVERSE", sec.company_id) in universe)

    out: list[HolderOut] = []
    for holder in store.list_holders():
        dates = [d for d in store.list_snapshot_dates(holder.holder_id, kind=holder.kind) if d <= today.isoformat()]
        if not dates:
            continue
        for h in store.load_snapshot(holder.holder_id, dates[-1], kind=holder.kind):
            if matches(h):
                out.append(HolderOut(holder_id=holder.holder_id, kind=holder.kind, as_of_date=dates[-1], weight_pct=h.weight_pct))
                break
    return out


def summary(session: Session, company_id: UUID, *, today: date, store=None) -> CompanySummary:
    """`store` is the portfolio store; without one `holders_available` is false."""
    c = session.get(m.Company, company_id)
    if c is None:
        raise LookupError(company_id)
    identifiers = _identifiers(session, [company_id])[company_id]
    counts = dict(
        session.execute(
            select(m.CompanyFact.status, func.count())
            .where(m.CompanyFact.company_id == company_id, m.CompanyFact.valid_to.is_(None))
            .group_by(m.CompanyFact.status)
        ).all()
    )
    holders = _holders(store, company_id, identifiers, today) if store is not None else []
    return CompanySummary(
        id=c.id, name=c.name, country=c.country, sector=c.sector, isic_code=c.isic_code,
        fiscal_year_end=c.fiscal_year_end, regimes=list(c.regimes or []), identifiers=identifiers,
        fact_counts={str(k.value): v for k, v in counts.items()},
        open_review_items=session.scalar(
            select(func.count()).select_from(m.ReviewItem).where(
                m.ReviewItem.company_id == company_id,
                m.ReviewItem.state.not_in([m.ItemState.FINAL, m.ItemState.SECOND_DONE]))
        ),
        documents=session.scalar(select(func.count()).select_from(m.Document).where(m.Document.company_id == company_id)),
        runs=session.scalar(select(func.count()).select_from(m.RunCompany).where(m.RunCompany.company_id == company_id)),
        holders=holders, holders_available=store is not None,
    )


def _primary_citations(session: Session, observation_ids: list[int]) -> dict[int, tuple[m.ValueCitation, str]]:
    out: dict[int, tuple[m.ValueCitation, str]] = {}
    rows = session.execute(
        select(m.ValueCitation, m.Document.title)
        .join(m.Document, m.Document.doc_id == m.ValueCitation.doc_id)
        .where(m.ValueCitation.observation_id.in_(observation_ids))
        .order_by(m.ValueCitation.role == m.CitationRole.PRIMARY, m.ValueCitation.id.desc())
    )
    for c, title in rows:  # later rows overwrite: primary (true sorts last), lowest id, ends up last
        out[c.observation_id] = (c, title)
    return out


def facts(
    session: Session, company_id: UUID, *, as_of: datetime | None = None, kind: m.FieldKind | None = None,
    field_id: str | None = None, period_end: date | None = None, limit: int = 100, offset: int = 0,
) -> list[CompanyFactRow]:
    f = m.CompanyFact
    where = [f.company_id == company_id]
    if as_of is None:
        where.append(f.valid_to.is_(None))
    else:
        where += [f.valid_from <= as_of, or_(f.valid_to.is_(None), f.valid_to > as_of)]
    if field_id:
        where.append(f.field_id == field_id)
    if period_end:
        where.append(f.period_end == period_end)
    query = (
        select(f, m.Field.kind, m.FieldObservation, m.DataSource, m.SourceLoad.fetched_at)
        .join(m.Field, m.Field.field_id == f.field_id)
        .join(m.FieldObservation, m.FieldObservation.id == f.observation_id)
        .outerjoin(m.DataSource, m.DataSource.source_id == m.FieldObservation.source_id)
        .outerjoin(m.SourceLoad, m.SourceLoad.load_id == m.FieldObservation.load_id)
        .where(and_(*where))
        .order_by(f.field_id, f.period_end.desc().nulls_last(), f.basis, f.id)
        .limit(limit).offset(offset)
    )
    if kind:
        query = query.where(m.Field.kind == kind)
    rows = session.execute(query).all()
    cites = _primary_citations(session, [r[2].id for r in rows])
    out = []
    for fact, fkind, obs, source, fetched_at in rows:
        if obs.source_kind == m.SourceKind.PROVIDER and source is not None:
            label = f"{source.name} · {fetched_at.date().isoformat()}" if fetched_at else source.name
        elif obs.id in cites:
            c, title = cites[obs.id]
            label = f"{title} p.{c.page}" if c.page is not None else title
        else:
            label = obs.run_id or obs.source_kind.value
        out.append(CompanyFactRow(
            fact_id=fact.id, field_id=fact.field_id, kind=fkind, period_end=fact.period_end, basis=fact.basis,
            value=fact.value, canonical_value=None if fact.canonical_value is None else float(fact.canonical_value),
            canonical_unit=fact.canonical_unit, status=fact.status, source_kind=obs.source_kind, source_label=label,
            licence=source.licence if source is not None else None, conflicting_sources=fact.conflicting_sources,
            valid_from=fact.valid_from, valid_to=fact.valid_to,
        ))
    return out


def trail(session: Session, fact_id: int) -> FactTrail:
    fact = session.get(m.CompanyFact, fact_id)
    if fact is None:
        raise LookupError(fact_id)
    f = m.CompanyFact
    versions = session.scalars(
        select(f).where(
            f.company_id == fact.company_id, f.field_id == fact.field_id, f.basis == fact.basis,
            f.period_end.is_not_distinct_from(fact.period_end),
        ).order_by(f.valid_from, f.id)
    ).all()
    out = []
    for v in versions:
        obs = session.get(m.FieldObservation, v.observation_id)
        citations = [
            CitationOut(doc_id=c.doc_id, title=d.title, page=c.page, quote=c.quote, char_start=c.char_start,
                        char_end=c.char_end, passage_id=c.passage_id, role=c.role, grounded=c.grounded,
                        company_id=d.universe_id or str(d.company_id), doc_type=d.doc_type,
                        source_filename=PurePath(d.local_path).name if d.local_path else None, source_url=d.source_url)
            for c, d in session.execute(
                select(m.ValueCitation, m.Document)
                .join(m.Document, m.Document.doc_id == m.ValueCitation.doc_id)
                .where(m.ValueCitation.observation_id == obs.id).order_by(m.ValueCitation.id))
        ]
        load = None
        if obs.load_id is not None:
            row = session.execute(
                select(m.DataSource.name, m.SourceLoad.fetched_at, m.SourceLoad.payload_uri)
                .join(m.SourceLoad, m.SourceLoad.source_id == m.DataSource.source_id)
                .where(m.SourceLoad.load_id == obs.load_id)).one()
            load = LoadOut(source_name=row[0], fetched_at=row[1], payload_uri=row[2])
        decisions = [
            DecisionOut(decision=d.decision, reviewer=d.reviewer, decided_at=d.decided_at, comment=d.comment)
            for d in session.scalars(
                select(m.ReviewDecision).join(m.ReviewItem, m.ReviewItem.id == m.ReviewDecision.review_item_id)
                .where(or_(
                    m.ReviewItem.observation_id == obs.id,
                    and_(  # a whole-record item (keyed by the company id) decides every reviewed observation of it
                        m.ReviewItem.observation_id.is_(None), obs.route == m.Route.REVIEW, m.ReviewItem.run_id == obs.run_id,
                        m.ReviewItem.company_id == obs.company_id, m.ReviewItem.item_key == m.ReviewItem.payload["company_id"].astext,
                    ),
                )).order_by(m.ReviewDecision.decided_at, m.ReviewDecision.id))
        ]
        out.append(FactVersion(
            fact_id=v.id, status=v.status, value=v.value, valid_from=v.valid_from, valid_to=v.valid_to,
            superseded_by=v.superseded_by,
            observation=ObservationOut(
                id=obs.id, source_kind=obs.source_kind, run_id=obs.run_id, value=obs.value, value_state=obs.value_state,
                unit=obs.unit, confidence=obs.confidence, route=obs.route, created_at=obs.created_at),
            citations=citations, load=load, decisions=decisions,
        ))
    return FactTrail(fact_id=fact.id, company_id=fact.company_id, field_id=fact.field_id,
                     period_end=fact.period_end, basis=fact.basis, versions=out)


# --- run-result queries (formerly api/company_results.py) -------------------------------------


def _company_of(session: Session, ref: str) -> UUID | None:
    """`ref` is what the old endpoints took, the universe company id; a UUID or `SCHEME:value` also works."""
    return resolve_ref(session, ref) or lookup(session, "UNIVERSE", ref)


def results_by_company(session: Session, run_type: str, ref: str) -> list[dict]:
    """Every result row for one company across every run of the type, newest run first."""
    cid = _company_of(session, ref)
    if cid is None:
        return []
    return list(session.scalars(
        select(m.RunResult.result).join(m.Run, m.Run.run_id == m.RunResult.run_id)
        .where(m.Run.run_type == run_type, m.RunResult.company_id == cid)
        .order_by(m.Run.created_at.desc(), m.RunResult.id)
    ))


def known_companies(session: Session, run_type: str) -> list[dict]:
    """Every company with a result in a run of this type, with the most recently saved name/ticker."""
    refs = session.scalars(
        select(m.RunCompany.ref)
        .join(m.Run, m.Run.run_id == m.RunCompany.run_id)
        .join(m.RunResult, and_(m.RunResult.run_id == m.RunCompany.run_id, m.RunResult.company_id == m.RunCompany.company_id))
        .where(m.Run.run_type == run_type)
        .order_by(m.Run.created_at, m.RunCompany.ordinal)  # later runs overwrite earlier ones below
    )
    seen = {r["company_id"]: {"company_id": r["company_id"], "name": r.get("name"), "ticker": r.get("ticker")} for r in refs if r.get("company_id")}
    return sorted(seen.values(), key=lambda c: c["company_id"])
