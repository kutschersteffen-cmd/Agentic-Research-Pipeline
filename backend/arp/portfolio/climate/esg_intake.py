"""ESG file intake: whole-file validation, then one observation per company and field. A load is keyed by
(provider, month); identical content is "unchanged", changed content appends new observations (latest wins)."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import openpyxl

from arp.holdings.file_source import Mapping, read_rows
from arp.holdings.intake import IntakeError
from arp.holdings.validate import RowError, _blank, parse_decimal
from arp.portfolio.climate import schemas
from arp.portfolio.loads import LoadRecord, latest_load, record_load
from arp.schemas.portfolio import DataPointObservation

MAPPINGS_DIR = Path(__file__).parent / "mappings"
FIELD_IDS = [
    schemas.FIELD_SCOPE1, schemas.FIELD_SCOPE2, schemas.FIELD_SCOPE3,
    schemas.FIELD_CARBON_INTENSITY, schemas.FIELD_EVIC, schemas.FIELD_GREEN_REVENUE_PCT,
]
# ponytail: company_id only; an `isin` column needs the security resolution step and is deferred.
ESG_TEMPLATE_COLUMNS = ["company_id", *FIELD_IDS]
MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


@dataclass
class ValidatedEsg:
    rows: list[dict] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)


@dataclass
class EsgIntakeResult:
    status: Literal["written", "unchanged"]
    rows: int


def load_esg_mapping(provider: str) -> Mapping:
    path = MAPPINGS_DIR / f"{provider}.json"
    if not re.fullmatch(r"[A-Za-z0-9_-]+", provider) or not path.is_file():
        raise ValueError(f"unknown mapping provider: {provider!r}")
    return Mapping.model_validate(json.loads(path.read_text(encoding="utf-8")))


def validate_esg(raw: list[dict], *, month: str, known_company_ids: set[str], decimal: str = ".") -> ValidatedEsg:
    if not MONTH.fullmatch(month):
        raise ValueError("month must be YYYY-MM")
    errors: list[RowError] = []
    if not raw:  # an empty "ok" load would unblock the monthly run on no data
        errors.append(RowError(None, "file", "no data rows"))
    if raw and not any("company_id" in r for r in raw):
        errors.append(RowError(None, "company_id", "missing required column"))
    rows: list[dict] = []
    seen: set[str] = set()
    for r in raw:
        n = r.get("_row")
        cid = "" if _blank(r.get("company_id")) else str(r["company_id"]).strip()
        if not cid:
            errors.append(RowError(n, "company_id", "required"))
        elif cid not in known_company_ids:
            errors.append(RowError(n, "company_id", f"unknown company_id {cid!r}"))
        elif cid in seen:
            errors.append(RowError(n, "company_id", "duplicate company"))
        seen.add(cid)
        row: dict = {"company_id": cid}
        for fid in FIELD_IDS:
            v = r.get(fid)
            if _blank(v):
                errors.append(RowError(n, fid, "required"))
                continue
            try:
                row[fid] = parse_decimal(v, decimal)
            except (ValueError, OverflowError):
                errors.append(RowError(n, fid, "not a number"))
        rows.append(row)
    return ValidatedEsg([] if errors else rows, errors)


def _hash(rows: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sorted(rows, key=lambda r: r["company_id"]), sort_keys=True).encode()).hexdigest()


def ingest_esg(store, validated: ValidatedEsg, *, provider: str, month: str, source_ref: str | None) -> EsgIntakeResult:
    if validated.errors:
        record_load(store, LoadRecord(kind="esg", source_id=provider, month=month, status="failed", content_hash="",
                                      detail=f"{len(validated.errors)} row errors"))
        raise IntakeError(422, "file rejected", validated.errors)
    digest = _hash(validated.rows)
    last = latest_load(store, "esg", provider, month)
    if last and last.status == "ok" and last.content_hash == digest:
        return EsgIntakeResult("unchanged", len(validated.rows))
    names = {f.field_id: f for f in schemas.build_climate_schema().fields}
    for r in validated.rows:
        for fid in FIELD_IDS:
            store.append_observation(DataPointObservation(
                company_id=r["company_id"], field_id=fid, field_name=names[fid].name, value=r[fid], unit=names[fid].unit,
                period=month, source="internal_api", notes=f"file:{source_ref}" if source_ref else "",
            ))
    record_load(store, LoadRecord(kind="esg", source_id=provider, month=month, status="ok", content_hash=digest,
                                  detail=f"{len(validated.rows)} rows"))
    return EsgIntakeResult("written", len(validated.rows))


def ingest_esg_bytes(store, data: bytes, filename: str, *, provider: str, month: str, source_ref: str | None) -> EsgIntakeResult:
    """The one path for upload and API pull: bytes -> read_rows -> validate_esg -> ingest_esg."""
    mapping = load_esg_mapping(provider)
    try:
        raw = read_rows(data, filename, mapping)
    except ValueError as exc:
        record_load(store, LoadRecord(kind="esg", source_id=provider, month=month, status="failed", content_hash="",
                                      detail=str(exc)[:200]))
        raise
    known = {c.company_id for c in store.list_companies()}
    validated = validate_esg(raw, month=month, known_company_ids=known, decimal=mapping.decimal)
    return ingest_esg(store, validated, provider=provider, month=month, source_ref=source_ref)


def template(fmt: Literal["csv", "xlsx"]) -> bytes:
    header = [load_esg_mapping("default").columns[c] for c in ESG_TEMPLATE_COLUMNS]
    if fmt == "csv":
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\n").writerow(header)
        return buf.getvalue().encode()
    wb = openpyxl.Workbook()
    wb.active.append(header)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
