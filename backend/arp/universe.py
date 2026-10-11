from __future__ import annotations

import csv
import json
from pathlib import Path

from arp.schemas.common import CompanyRef


def load_company_universe(path: str | Path) -> list[CompanyRef]:
    """Loads the user-supplied starting company universe from CSV or JSON.

    CSV columns: company_id, name, ticker, website, cik, lei, isin, country, sector,
    fiscal_year_end (MM-DD, e.g. 03-31; resolves "FY2024"-style period
    labels) -- company_id, name required; the rest optional. JSON: a list of objects
    with the same fields. This is intentionally the single entry point the
    API, CLI, and scheduler all use, so a universe file behaves identically
    everywhere.
    """
    path = Path(path)
    if path.suffix.lower() == ".json":
        rows = json.loads(path.read_text())
    elif path.suffix.lower() == ".csv":
        with path.open(newline="") as f:
            rows = list(csv.DictReader(f))
    else:
        raise ValueError(f"Unsupported universe file type: {path.suffix}")

    companies: list[CompanyRef] = []
    for row in rows:
        clean = {k: (v if v not in ("", None) else None) for k, v in row.items()}
        companies.append(CompanyRef(**clean))
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
