"""Company registry: resolves a company row (universe file, provider record) to one company UUID
through identifier aliases (`company_identifiers`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from arp.db.models import Company, CompanyIdentifier, IdScheme
from arp.schemas.common import CompanyRef
from arp.storage.postgres_models import Base


@dataclass
class Resolution:
    company_id: UUID | None
    created: bool
    conflict: list[UUID] = field(default_factory=list)


def normalise_identifier(scheme: str, value: str) -> str:
    v = "".join(value.split()).upper()
    return v.lstrip("0") if scheme == "CIK" else v


def identifiers_of(company: CompanyRef) -> list[tuple[IdScheme, str]]:
    pairs = [
        (IdScheme.LEI, company.lei),
        (IdScheme.ISIN, company.isin),
        (IdScheme.CIK, company.cik),
        (IdScheme.UNIVERSE, company.company_id),
        (IdScheme.TICKER, company.ticker),
    ]
    return [(s, normalise_identifier(s, v)) for s, v in pairs if v and normalise_identifier(s, v)]


def _active(session: Session, scheme: str, value: str) -> UUID | None:
    return session.scalar(
        select(CompanyIdentifier.company_id).where(
            CompanyIdentifier.scheme == str(scheme),
            CompanyIdentifier.value == normalise_identifier(scheme, value),
            CompanyIdentifier.valid_to.is_(None),
        )
    )


def lookup(session: Session, scheme: IdScheme, value: str) -> UUID | None:
    return _active(session, scheme, value)


def resolve(
    session: Session, ids: list[tuple[IdScheme, str]], *, name: str, allow_create: bool, attrs: dict | None = None
) -> Resolution:
    ids = [(s, normalise_identifier(s, v)) for s, v in ids if v and normalise_identifier(s, v)]
    found = {s_v: _active(session, *s_v) for s_v in ids}
    owners = list(dict.fromkeys(c for c in found.values() if c is not None))
    if len(owners) > 1:
        return Resolution(None, False, owners)
    if owners:
        company_id, created = owners[0], False
    elif allow_create and ids:
        created = True
        company = Company(name=name, **(attrs or {}))
        session.add(company)
        session.flush()
        company_id = company.id
    else:
        return Resolution(None, False, [])
    for scheme, value in ids:
        if found[(scheme, value)] is None:
            session.add(CompanyIdentifier(company_id=company_id, scheme=str(scheme), value=value))
    session.flush()
    return Resolution(company_id, created, [])


def resolve_company(session: Session, company: CompanyRef) -> Resolution:
    attrs = {
        k: v for k, v in company.model_dump(include={"country", "sector", "isic_code", "fiscal_year_end", "regimes"}).items() if v
    }
    return resolve(session, identifiers_of(company), name=company.name, allow_create=True, attrs=attrs)


def ensure_universe_company(session: Session, universe_id: str, *, name: str | None = None) -> UUID:
    res = resolve(session, [(IdScheme.UNIVERSE, universe_id)], name=name or universe_id, allow_create=True)
    assert res.company_id is not None
    return res.company_id


def merge(session: Session, keep: UUID, drop: UUID) -> None:
    """Re-points every row that references `drop` at `keep`, then records `drop` MERGED_INTO `keep`."""
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_keys:
            if fk.column.table.name == "companies" and fk.column.name == "id":
                session.execute(update(table).where(fk.parent == drop).values({fk.parent.name: keep}))
    session.add(
        CompanyIdentifier(
            company_id=drop, scheme=IdScheme.MERGED_INTO, value=normalise_identifier(IdScheme.MERGED_INTO, str(keep))
        )
    )
    session.flush()
