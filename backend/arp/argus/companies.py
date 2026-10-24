"""Step 1: register a company list against the central company id (`companies.id`).

LEI, ISIN and CIK match or create a company; the list's own `company_id` becomes a `USER` identifier on it."""

from __future__ import annotations

import csv
import io
import json

from sqlalchemy.orm import Session

from arp.argus.flows import ArgusFlow
from arp.db.companies import lookup, normalise_identifier, resolve
from arp.db.models import CompanyIdentifier, IdScheme
from arp.schemas.common import CompanyRef

NO_IDENTIFIER = "No identifier: add an ISIN, LEI or CIK"
CONFLICT = "Identifiers match more than one company"
_FIELDS = ("company_id", "name", "ticker", "website", "cik", "lei", "isin", "country", "sector")


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


def _standard_ids(row: dict) -> list[tuple[IdScheme, str]]:
    return [(s, row[s.lower()]) for s in (IdScheme.LEI, IdScheme.ISIN, IdScheme.CIK) if row.get(s.lower())]


def register(session: Session, row: dict) -> CompanyRef | None:
    """The row as a company, with `entity_id` set when it matches; None for a row with nothing to name it by."""
    fields = {k: row[k] for k in _FIELDS if row.get(k)}
    own_id = fields.get("company_id")
    name = fields.get("name") or own_id or next((v for _, v in _standard_ids(row)), None)
    if not name:
        return None
    ids = _standard_ids(row)
    entity_id = None
    if ids:
        attrs = {k: fields[k] for k in ("sector", "country") if k in fields}
        entity_id = resolve(session, ids, name=name, allow_create=True, attrs=attrs).company_id  # None on a conflict
    elif own_id:
        entity_id = lookup(session, IdScheme.USER, own_id) or lookup(session, IdScheme.UNIVERSE, own_id)
    if entity_id and own_id and normalise_identifier(IdScheme.USER, own_id) and lookup(session, IdScheme.USER, own_id) is None:
        session.add(CompanyIdentifier(company_id=entity_id, scheme=str(IdScheme.USER), value=normalise_identifier(IdScheme.USER, own_id)))
        session.flush()
    return CompanyRef(**{**fields, "name": name, "company_id": own_id or str(entity_id or name), "entity_id": entity_id})


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
