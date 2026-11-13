from __future__ import annotations

import csv
import json
from pathlib import Path

from pydantic import ValidationError

from arp.errors import ClientInputError
from arp.research.indirect_exposure.nace import nace_known, normalise_nace
from arp.schemas.common import CompanyRef


class UniverseRejected(ClientInputError):
    """A universe file holds a sector code that is not valid; `str(e)` is the user-facing message."""


def check_sector_codes(company: CompanyRef) -> CompanyRef:
    """Normalises `nace_code` and validates it and `gics_code`; blank codes count as absent."""
    update: dict[str, str | None] = {}
    if company.nace_code is not None:
        raw = company.nace_code.strip()
        code = normalise_nace(raw) if raw else None
        # "7.29" would normalise to "72.9"; the message shows what the user wrote.
        if code is not None and not nace_known(code, company.nace_rev):
            raise UniverseRejected(
                f"unknown NACE Rev. {company.nace_rev} code '{raw}' for company '{company.company_id}'"
            )
        update["nace_code"] = code
    if company.gics_code is not None:
        raw = company.gics_code.strip()
        if raw and not (raw.isascii() and raw.isdigit() and len(raw) in (2, 4, 6, 8)):
            raise UniverseRejected(f"bad GICS code '{raw}' for company '{company.company_id}'")
        update["gics_code"] = raw or None
    return company.model_copy(update=update)


def load_company_universe(path: str | Path) -> list[CompanyRef]:
    """Loads the user-supplied starting company universe from CSV or JSON.

    CSV columns: company_id, entity_id, name, ticker, website, cik, lei, isin, country, sector,
    isic_code, nace_code, nace_rev, gics_code, regimes, fiscal_year_end (MM-DD, e.g. 03-31;
    resolves "FY2024"-style period labels) -- company_id, name required; the rest optional. JSON: a list of objects
    with the same fields. This is intentionally the single entry point the
    API, CLI, and scheduler all use, so a universe file behaves identically
    everywhere.
    """
    path = Path(path)
    if path.suffix.lower() == ".json":
        rows = json.loads(path.read_text())
    elif path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    else:
        raise ValueError(f"Unsupported universe file type: {path.suffix}")

    companies: list[CompanyRef] = []
    seen: set[str] = set()
    for n, row in enumerate(rows, start=1):  # rows counted from 1 at the first data row
        clean = {k: (v if v not in ("", None) else None) for k, v in row.items()}
        if clean.get("nace_rev") is None:
            clean.pop("nace_rev", None)  # blank -> default "2"
        for k in ("nace_code", "nace_rev", "gics_code"):  # JSON numbers (7.29) are validated as text
            if clean.get(k) is not None:
                clean[k] = str(clean[k])
        try:
            ref = CompanyRef(**clean)
        except ValidationError as exc:  # the first bad field of the first bad row, in words, not pydantic's text
            field = str(exc.errors()[0]["loc"][0])
            problem = "is required" if clean.get(field) is None else "is not valid"
            raise UniverseRejected(f"Row {n}: {field} {problem}.") from None
        company = check_sector_codes(ref)
        if company.company_id in seen:
            raise UniverseRejected(f"duplicate company_id '{company.company_id}'")
        seen.add(company.company_id)
        companies.append(company)
    return companies


def resolve_universe(companies: list[CompanyRef], session) -> tuple[list[CompanyRef], list[dict]]:
    """Sets `entity_id` on each company via the registry. Identity conflicts are returned (not resolved)."""
    from arp.db.companies import resolve_company

    resolved: list[CompanyRef] = []
    conflicts: list[dict] = []
    for c in companies:
        r = resolve_company(session, c)
        if r.conflict:
            conflicts.append({"kind": "identity_conflict", "company_id": c.company_id, "conflict": [str(u) for u in r.conflict]})
        else:
            resolved.append(c.model_copy(update={"entity_id": r.company_id}))
    return resolved, conflicts
