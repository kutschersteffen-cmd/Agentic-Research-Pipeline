"""Step 1: register a company list against the central company id (`companies.id`).

LEI, ISIN and CIK match or create a company; the list's own `company_id` becomes a `USER` identifier on it."""

from __future__ import annotations

import asyncio
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
TICKER_UNLISTED = "Ticker {ticker} is not listed at the SEC: add an ISIN, LEI or CIK"
SEC_UNREADABLE = "The SEC ticker list could not be read: add an ISIN, LEI or CIK"
_FIELDS = ("company_id", "name", "ticker", "website", "cik", "lei", "isin", "country", "sector", "isic_code")


def parse_rows(filename: str, data: bytes) -> list[dict]:
    """CSV or JSON rows; unlike `load_company_universe`, `company_id` may be missing."""
    text = data.decode("utf-8-sig")
    if filename.lower().endswith(".json"):
        rows = json.loads(text)
        if not isinstance(rows, list):
            raise ValueError("A JSON list must be an array of companies.")
    elif filename.lower().endswith(".csv"):
        try:
            rows = list(csv.DictReader(io.StringIO(text)))
        except csv.Error as exc:  # a field over the reader's size limit, a NUL: not a ValueError
            raise ValueError(str(exc)) from exc
    else:
        raise ValueError("Upload a .csv or .json file.")
    return [{k.strip().lower(): str(v).strip() for k, v in r.items() if k and v not in (None, "")} for r in rows if isinstance(r, dict)]


# The shape of each identifier. A spreadsheet placeholder ("N/A", "-", "tbd") is not one: taken as an ISIN it
# matched every other placeholder row to one company. Check digits are not tested, so a typo still registers.
_SHAPE = {IdScheme.LEI: r"[A-Z0-9]{18}[0-9]{2}", IdScheme.ISIN: r"[A-Z]{2}[A-Z0-9]{9}[0-9]", IdScheme.CIK: r"[0-9]{1,10}"}


def _standard_ids(row: dict) -> list[tuple[IdScheme, str]]:
    return [(s, row[s.lower()]) for s in _SHAPE
            if row.get(s.lower()) and re.fullmatch(_SHAPE[s], "".join(row[s.lower()].split()).upper())]


async def ticker_ciks(rows: list[dict], edgar) -> dict[int, str]:
    """Gives each row with a ticker and no valid ISIN, LEI or CIK the CIK the SEC lists for that ticker (`edgar` is
    an `EdgarDocumentSource`). The ticker itself never reaches matching: tickers repeat across exchanges. A row that
    has an identifier is not looked up, so a wrong-exchange ticker cannot add a second company's CIK to it.
    Returns, per row index, why a lookup gave nothing; the row is still added."""
    problems: dict[int, str] = {}
    unreadable = False
    for i, row in enumerate(rows):
        ticker = row.get("ticker")
        if not ticker or _standard_ids(row):
            continue
        cik = None
        if not unreadable:  # one failed read is enough: the next row would wait for the same timeout
            try:
                cik = await asyncio.wait_for(edgar.resolve_cik(ticker), 10)
            except Exception:  # noqa: BLE001 -- the SEC is unreachable, slow, or its list unreadable
                unreadable = True
        if cik:
            row["cik"] = cik
        else:
            problems[i] = SEC_UNREADABLE if unreadable else TICKER_UNLISTED.format(ticker=ticker)
    return problems


def register(session: Session, row: dict, *, keep: str | None = None) -> CompanyRef | None:
    """The row as a company, with `entity_id` set when it matches; None for a row with nothing to name it by.
    `keep` is the key the row already has in a flow (an edit, an identity result). It stays the row's key unless
    the row now matches a company that is stored under another key."""
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
    if keep is None and entity_id:
        key = _key(session, entity_id, own_id)
    elif keep is None:
        # A list id made of digits is a row number, and every list has a row 1: such a row is keyed by its name
        # and that id together. An id with a letter (`aapl`) stays the key: documents and earlier runs are filed under it.
        key = f"{name}-{own_id}" if own_id and own_id.isascii() and own_id.isdigit() else own_id or name
    elif entity_id and _universe_id(session, entity_id) not in (None, normalise_identifier(IdScheme.UNIVERSE, keep)):
        key = _key(session, entity_id, None)
    else:
        if entity_id:  # a company with no universe id yet is filed under the row's key from now on
            _key(session, entity_id, keep)
        key = keep
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


def problem_of(company: CompanyRef, ticker_problem: str | None = None) -> str | None:
    """Why an unmatched company has no central id: its LEI/ISIN/CIK point at different companies, or it has none
    (`ticker_problem`: its ticker was looked up and gave none)."""
    if company.entity_id:
        return None
    return CONFLICT if company.lei or company.isin or company.cik else ticker_problem or NO_IDENTIFIER


class Refused(Exception):
    """A changed row that must not replace the stored one. The caller rolls the register back."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status, self.detail = status, detail


def reregister(session: Session, flow: ArgusFlow, old: CompanyRef, changes: dict, *, has_files: bool) -> CompanyRef:
    """`old` with `changes` (name, ticker, website, ISIN, LEI, CIK; None clears), registered again by the rules of
    adding. Every other column of the row is kept. The row keeps its key unless it now matches a company stored
    under another key; with files listed for it in the flow that is refused, since the files would stay behind."""
    row = {k: v for k, v in {**old.model_dump(mode="json"), **changes, "company_id": None}.items() if v}
    new = register(session, row, keep=old.company_id)
    if new is None:
        raise Refused(400, "A company needs a name.")
    twin = next((c for c in flow.companies if c is not old and (
        c.company_id == new.company_id or (c.entity_id and c.entity_id == new.entity_id))), None)
    if twin:
        raise Refused(400, f"{twin.name} is already in this extraction.")
    if has_files and new.company_id != old.company_id:
        raise Refused(409, f"{old.name} has files in this extraction. Remove the company and add it again with the identifier.")
    return old.model_copy(update={k: getattr(new, k) for k in (*_FIELDS, "entity_id")})


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
