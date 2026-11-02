"""The security master: the tool's golden source mapping securities (and issuer identifiers) to internal issuer ids.

Loaded only here, from Data Hub (file now, API later); everything else reads the identifier map it writes. Matching is
exact: an identifier the master holds resolves to its issuer, anything else is unmatched -- never guessed by name."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date

from arp.holdings.file_source import Mapping, read_rows
from arp.holdings.validate import RowError, isin_is_valid, iso_date
from arp.portfolio.loads import LoadRecord, record_load
from arp.schemas.common import CompanyRef, now_iso
from arp.schemas.issuer import IdentifierMap, lei_is_valid, normalise_lei
from arp.storage.atomic_io import atomic_write_text
from arp.storage.identifier_map import IdentifierMapStore, normalise_identifier
from arp.storage.issuer_sectors import IssuerSectorStore
from arp.universe import UniverseRejected, check_sector_codes

# Column -> identifier scheme. The first four identify a security, the last three its issuer (PermID: Refinitiv's).
SCHEMES = {"isin": "ISIN", "cusip": "CUSIP", "sedol": "SEDOL", "figi": "FIGI", "lei": "LEI", "cik": "CIK", "permid": "PERMID"}
SECTOR_COLUMNS = ("nace_code", "nace_rev", "isic_code", "gics_code")
COLUMNS = ("issuer_id", "issuer_name", *SCHEMES, "valid_from", "valid_to", *SECTOR_COLUMNS)
_MAPPING = Mapping(provider="security_master", columns={c: c for c in COLUMNS})


def _format_error(scheme: str, value: str) -> str | None:
    ok = {
        "ISIN": isin_is_valid(value),
        "LEI": lei_is_valid(value),
        "CUSIP": len(value) == 9 and value.isalnum(),
        "SEDOL": len(value) == 7 and value.isalnum(),
        "FIGI": len(value) == 12 and value.startswith("BBG") and value.isalnum(),
        "CIK": value.isdigit() and len(value) <= 10,
        "PERMID": value.isdigit() and len(value) <= 15,
    }[scheme]
    return None if ok else f"not a valid {scheme}"


def parse(data: bytes, filename: str) -> tuple[list[IdentifierMap], list[RowError]]:
    rows, errors, _ = parse_with_sectors(data, filename)
    return rows, errors


def parse_with_sectors(data: bytes, filename: str) -> tuple[list[IdentifierMap], list[RowError], dict[str, dict[str, str]]]:
    """Rows of the master file as identifier-map rows, or every problem found. One file row is one security (or one
    issuer with only issuer identifiers); each identifier on it becomes a row pointing at its `issuer_id`."""
    out: list[IdentifierMap] = []
    errors: list[RowError] = []
    seen: dict[str, dict[str, str]] = {}  # issuer -> column -> first value
    first_row: dict[str, int] = {}
    names: dict[str, str] = {}
    for r in read_rows(data, filename, _MAPPING):
        n = r["_row"]
        issuer = str(r.get("issuer_id") or "").strip()
        if not issuer:
            errors.append(RowError(n, "issuer_id", "missing"))
            continue
        valid_from, valid_to = (str(r[c]).strip() if r.get(c) not in (None, "") else None for c in ("valid_from", "valid_to"))
        bad_dates = [c for c, v in (("valid_from", valid_from), ("valid_to", valid_to)) if v and not iso_date(v)]
        errors += [RowError(n, c, "must be YYYY-MM-DD") for c in bad_dates]
        if not bad_dates and valid_from and valid_to and valid_from >= valid_to:
            errors.append(RowError(n, "valid_to", "must be after valid_from"))
        first_row.setdefault(issuer, n)
        names.setdefault(issuer, str(r.get("issuer_name") or "").strip())
        for col in SECTOR_COLUMNS:
            v = str(r.get(col) or "").strip()
            if v and seen.setdefault(issuer, {}).setdefault(col, v) != v:
                errors.append(RowError(n, col, f"issuer '{issuer}' has two different {col} values"))
        ids = 0
        for col, scheme in SCHEMES.items():
            raw = str(r.get(col) or "").strip()
            if not raw:
                continue
            value = normalise_lei(raw) if scheme == "LEI" else normalise_identifier(scheme, raw)
            if problem := _format_error(scheme, value):
                errors.append(RowError(n, col, problem))
                continue
            ids += 1
            out.append(IdentifierMap(issuer_key=issuer, scheme=scheme, value=value, valid_from=valid_from, valid_to=valid_to))
        if ids == 0 and not any(e.row == n for e in errors):
            errors.append(RowError(n, None, "no identifier: give at least one of " + ", ".join(SCHEMES)))
    sectors = _checked_sectors(seen, first_row, names, errors)
    return _dedupe(out), errors + _conflicts(out), sectors


def _checked_sectors(seen, first_row, names, errors: list[RowError]) -> dict[str, dict[str, str]]:
    """Each issuer's sector codes, normalised and validated like a universe file's; problems join `errors`."""
    out: dict[str, dict[str, str]] = {}
    for issuer, cols in seen.items():
        if any(e.message.startswith(f"issuer '{issuer}' has two") for e in errors):  # already reported
            continue
        rev = cols.get("nace_rev", "")
        if rev and rev not in ("2", "2.1"):
            errors.append(RowError(first_row[issuer], "nace_rev", "must be 2 or 2.1"))
            continue
        try:
            c = check_sector_codes(CompanyRef(company_id=issuer, name=names[issuer], nace_code=cols.get("nace_code"),
                                              nace_rev=rev or "2", isic_code=cols.get("isic_code"), gics_code=cols.get("gics_code")))
        except UniverseRejected as e:
            errors.append(RowError(first_row[issuer], "nace_code" if str(e).startswith("unknown NACE") else "gics_code", str(e)))
            continue
        row = {"nace_code": c.nace_code, "isic_code": c.isic_code, "gics_code": c.gics_code}
        if c.nace_code or rev:
            row["nace_rev"] = c.nace_rev  # an empty cell next to a nace_code means Rev. 2
        if row := {k: v for k, v in row.items() if v}:
            out[issuer] = row
    return out


def _dedupe(rows: list[IdentifierMap]) -> list[IdentifierMap]:
    """An issuer's LEI repeats on every one of its securities' rows: keep it once."""
    seen: set[tuple] = set()
    keep = []
    for m in rows:
        k = (m.issuer_key, m.scheme, m.value, m.valid_from, m.valid_to)
        if k not in seen:
            seen.add(k)
            keep.append(m)
    return keep


def _conflicts(rows: list[IdentifierMap]) -> list[RowError]:
    """One identifier pointing at two issuers over overlapping dates would make the match ambiguous: refused."""
    by_id: dict[tuple[str, str], list[IdentifierMap]] = {}
    for m in rows:
        by_id.setdefault((m.scheme, m.value), []).append(m)
    errors = []
    for (scheme, value), ms in by_id.items():
        for i, a in enumerate(ms):
            for b in ms[i + 1:]:
                overlap = (a.valid_to is None or b.valid_from is None or b.valid_from < a.valid_to) and (
                    b.valid_to is None or a.valid_from is None or a.valid_from < b.valid_to)
                if a.issuer_key != b.issuer_key and overlap:
                    errors.append(RowError(None, scheme.lower(), f"{scheme} {value} maps to both {a.issuer_key} and {b.issuer_key}"))
    return errors


def load(store, idmap: IdentifierMapStore, data: bytes, filename: str) -> dict:
    """Replaces the identifier map with the file's rows, or changes nothing and raises ValueError listing the
    problems. The previous master is kept next to it, named by load time."""
    rows, errors, sectors = parse_with_sectors(data, filename)
    digest = hashlib.sha256(data).hexdigest()
    if errors or not rows:
        record_load(store, LoadRecord(kind="security_master", source_id="file", month=date.today().isoformat()[:7],
                                      status="failed", content_hash=digest, detail=f"{len(errors)} errors"))
        raise MasterRejected(errors or [RowError(None, None, "the file has no rows")])
    if idmap.path.exists():
        shutil.copy2(idmap.path, idmap.path.with_name(f"{idmap.path.stem}.{now_iso().replace(':', '')}.jsonl"))
    atomic_write_text(idmap.path, "".join(json.dumps(m.model_dump(mode="json")) + "\n" for m in rows))
    IssuerSectorStore(idmap.path.with_name("issuer_sectors.json")).replace(sectors)
    issuers = len({m.issuer_key for m in rows})
    record_load(store, LoadRecord(kind="security_master", source_id="file", month=date.today().isoformat()[:7], status="ok",
                                  content_hash=digest, detail=f"{len(rows)} identifiers, {issuers} issuers"))
    return {"identifiers": len(rows), "issuers": issuers, "content_hash": digest}


class MasterRejected(ValueError):
    def __init__(self, errors: list[RowError]) -> None:
        super().__init__(f"security master rejected: {len(errors)} problems")
        self.errors = errors


def status(store, idmap: IdentifierMapStore) -> dict:
    """The current master (counts per scheme) and its last load attempt."""
    rows = idmap.rows()
    loads = [e for e in store.list_governance_events() if e.get("event_type") == "load_recorded" and e.get("kind") == "security_master"]
    return {
        "issuers": len({m.issuer_key for m in rows}),
        "identifiers": {s: sum(1 for m in rows if m.scheme == s) for s in SCHEMES.values()},
        "last_load": loads[-1] if loads else None,
    }


def unmatched(store, idmap: IdentifierMapStore) -> list[dict]:
    """Securities held in a latest snapshot that the current master does not map to exactly one issuer, per holder.
    Fixed by correcting the master, then reloading the holdings."""
    out = []
    for h in store.list_holders():
        if not h.as_of:
            continue
        for row in store.load_snapshot(h.holder_id, h.as_of, kind=h.kind):
            keys = idmap.resolve("ISIN", row.isin, on=h.as_of) if row.isin else []
            if len(keys) != 1:
                out.append({"holder_id": h.holder_id, "kind": h.kind, "as_of": h.as_of, "isin": row.isin,
                            "security_id": row.security_id, "reason": "ambiguous" if keys else "not in security master",
                            "issuer_key": row.issuer_key, "candidates": keys})
    return out
