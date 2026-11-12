"""Step 1: register a company list against the central company id (`companies.id`).

LEI, ISIN and CIK match or create a company; the list's own `company_id` becomes a `USER` identifier on it."""

from __future__ import annotations

import csv
import io
import json
import re

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from arp.argus.flows import ArgusFlow, safe_key
from arp.db.companies import lookup, normalise_identifier, resolve
from arp.db.models import Company, CompanyIdentifier, IdScheme
from arp.schemas.common import CompanyRef

NO_IDENTIFIER = "No identifier: add an ISIN, LEI or CIK"
CONFLICT = "Identifiers match more than one company"
_FIELDS = ("company_id", "name", "ticker", "website", "cik", "lei", "isin", "country", "sector", "isic_code")


def parse_rows(filename: str, data: bytes) -> list[dict]:
    """CSV or JSON rows; unlike `load_company_universe`, `company_id` may be missing."""
    text = data.decode("utf-8-sig")
    if filename.lower().endswith(".json"):
        rows = json.loads(text)
        if not isinstance(rows, list):
            raise ValueError("A JSON list must be an array of companies.")
    elif filename.lower().endswith(".csv"):
        rows = list(csv.DictReader(io.StringIO(text)))
    else:
        raise ValueError("Upload a .csv or .json file.")
    return [{k.strip().lower(): str(v).strip() for k, v in r.items() if k and v not in (None, "")} for r in rows if isinstance(r, dict)]


# The shape of each identifier. A spreadsheet placeholder ("N/A", "-", "tbd") is not one: taken as an ISIN it
# matched every other placeholder row to one company. Check digits are not tested, so a typo still registers.
_SHAPE = {IdScheme.LEI: r"[A-Z0-9]{18}[0-9]{2}", IdScheme.ISIN: r"[A-Z]{2}[A-Z0-9]{9}[0-9]", IdScheme.CIK: r"[0-9]{1,10}"}


def _standard_ids(row: dict) -> list[tuple[IdScheme, str]]:
    return [(s, row[s.lower()]) for s in _SHAPE
            if row.get(s.lower()) and re.fullmatch(_SHAPE[s], "".join(row[s.lower()].split()).upper())]


def register(session: Session, row: dict) -> CompanyRef | None:
    """The row as a company, with `entity_id` set when it matches; None for a row with nothing to name it by."""
    ids = _standard_ids(row)
    valid = {s.lower() for s, _ in ids}
    fields = {k: row[k] for k in _FIELDS if row.get(k) and (k not in ("lei", "isin", "cik") or k in valid)}
    own_id = fields.get("company_id")
    name = fields.get("name") or own_id or next((v for _, v in ids), None)
    if not name:
        return None
    entity_id = None
    if ids:  # only LEI/ISIN/CIK match: a list's own ids are per list, so they never pick a company
        attrs = {k: fields[k] for k in ("sector", "country", "isic_code") if k in fields}
        entity_id = resolve(session, ids, name=name, allow_create=True, attrs=attrs).company_id  # None on a conflict
        if entity_id and fields.get("isic_code"):  # an existing company gets the code only if it has none
            session.execute(update(Company).where(Company.id == entity_id, Company.isic_code.is_(None))
                            .values(isic_code=fields["isic_code"]))
    if entity_id and own_id and normalise_identifier(IdScheme.USER, own_id):
        owner = lookup(session, IdScheme.USER, own_id)
        if owner is None:
            try:
                with session.begin_nested():
                    session.add(CompanyIdentifier(company_id=entity_id, scheme=str(IdScheme.USER),
                                                  value=normalise_identifier(IdScheme.USER, own_id)))
            except IntegrityError:  # another upload registered it first
                owner = "taken"
        if owner not in (None, entity_id):
            own_id = None  # another company's id: never the key two rows could share
    # Earlier runs and documents are filed under the universe id (until they are filed by central id).
    key = _key(session, entity_id, own_id) if entity_id else own_id or name
    return CompanyRef(**{**fields, "name": name, "company_id": safe_key(key), "entity_id": entity_id})


def _key(session: Session, entity_id, own_id: str | None) -> str:
    """A matched company's key: its universe id. A company without one gets its key recorded as its universe id,
    so documents registered under the key land on this company (not on a new one named after the key) and
    every later flow finds the same key."""
    central = str(entity_id)
    universe = _universe_id(session, entity_id)
    for candidate in (own_id, central) if universe is None else ():
        value = normalise_identifier(IdScheme.UNIVERSE, candidate) if candidate else ""
        if not value or lookup(session, IdScheme.UNIVERSE, candidate) is not None:
            continue
        try:
            with session.begin_nested():
                session.add(CompanyIdentifier(company_id=entity_id, scheme=str(IdScheme.UNIVERSE), value=value))
        except IntegrityError:  # another upload took it first
            continue
        universe = value
        break
    return central if universe in (None, normalise_identifier(IdScheme.UNIVERSE, central)) else universe


def _universe_id(session: Session, entity_id) -> str | None:
    """The id earlier runs and documents of this company are filed under (until documents are filed by central id)."""
    return session.scalar(select(CompanyIdentifier.value).where(
        CompanyIdentifier.company_id == entity_id, CompanyIdentifier.scheme == str(IdScheme.UNIVERSE),
        CompanyIdentifier.valid_to.is_(None)).order_by(CompanyIdentifier.id).limit(1))


def problem_of(company: CompanyRef) -> str | None:
    """Why an unmatched company has no central id: its LEI/ISIN/CIK point at different companies, or it has none."""
    if company.entity_id:
        return None
    return CONFLICT if company.lei or company.isin or company.cik else NO_IDENTIFIER


def add_companies(flow: ArgusFlow, companies: list[CompanyRef]) -> None:
    key = lambda c: str(c.entity_id) if c.entity_id else c.company_id  # noqa: E731
    seen = {key(c) for c in flow.companies}
    for c in companies:
        if key(c) not in seen:
            seen.add(key(c))
            flow.companies.append(c)


def with_register_ids(session: Session, company: CompanyRef) -> CompanyRef:
    """The company with the LEI and CIK the register holds for it filled in where the list gave none (discovery needs them)."""
    if not company.entity_id:
        return company
    have = dict(session.execute(select(CompanyIdentifier.scheme, CompanyIdentifier.value).where(
        CompanyIdentifier.company_id == company.entity_id, CompanyIdentifier.valid_to.is_(None),
        CompanyIdentifier.scheme.in_((str(IdScheme.LEI), str(IdScheme.CIK)))).order_by(CompanyIdentifier.id.desc())).all())
    return company.model_copy(update={"lei": company.lei or have.get(str(IdScheme.LEI)),
                                      "cik": company.cik or have.get(str(IdScheme.CIK))})
