"""ESG file intake: whole-file validation, then one observation per company and field. A load is keyed by
(provider, month); identical content is "unchanged", changed content appends new observations (latest wins)."""

from __future__ import annotations

import calendar
import csv
import hashlib
import io
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

import openpyxl

from arp.db.fields import normalise_metric_code
from arp.db.models import IdScheme, Licence
from arp.db.providers import IngestReport, ProviderRow, ensure_source, ingest_rows, record_load
from arp.db.session import transaction
from arp.holdings.file_source import Mapping, read_rows
from arp.holdings.intake import IntakeError
from arp.holdings.validate import RowError, _blank, parse_decimal
from arp.portfolio.climate import schemas
from arp.portfolio.loads import LoadRecord, latest_load
from arp.portfolio.loads import record_load as record_file_load
from arp.schemas.portfolio import DataPointObservation

logger = logging.getLogger(__name__)

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
        record_file_load(store, LoadRecord(kind="esg", source_id=provider, month=month, status="failed", content_hash="",
                                           detail=f"{len(validated.errors)} row errors"))
        raise IntakeError(422, "file rejected", validated.errors)
    _record_provider_load(validated.rows, provider=provider, month=month, source_ref=source_ref)
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
    record_file_load(store, LoadRecord(kind="esg", source_id=provider, month=month, status="ok", content_hash=digest,
                                       detail=f"{len(validated.rows)} rows"))
    return EsgIntakeResult("written", len(validated.rows))


def _month_end(month: str) -> date:
    y, m = map(int, month.split("-"))
    return date(y, m, calendar.monthrange(y, m)[1])


def _provider_rows(payload: bytes) -> list[ProviderRow]:
    """The stored payload (month + validated rows) as provider rows; also used to re-ingest a load."""
    doc = json.loads(payload)
    period_end = _month_end(doc["month"])
    names = {f.field_id: f for f in schemas.build_climate_schema().fields}
    return [
        ProviderRow(issuer_ids=[(IdScheme.UNIVERSE, r["company_id"])], metric_code=fid, metric_name=names[fid].name,
                    unit=names[fid].unit, data_type="number", period_end=period_end, value=r[fid])
        for r in doc["rows"] for fid in FIELD_IDS
    ]


def esg_source_slug(provider: str) -> str:
    return f"esg_{normalise_metric_code(provider)}"


def esg_payload(rows: list[dict], month: str) -> bytes:
    """The stored payload of a load; its sha256 is the load's natural key."""
    return json.dumps({"month": month, "rows": sorted(rows, key=lambda r: r["company_id"])}, sort_keys=True).encode()


def record_esg_load(session, rows: list[dict], *, provider: str, month: str, source_ref: str | None) -> IngestReport | None:
    """The file as a `kind = file` provider source (`esg_<provider>`): one load per distinct payload,
    observations on `prov:esg_<provider>:<field>`. Universe ids never create companies. None when
    the payload is unchanged."""
    payload = esg_payload(rows, month)
    source_id = ensure_source(session, esg_source_slug(provider), name=f"ESG file ({provider})",
                              kind="file", licence=Licence.INTERNAL_ONLY, id_scheme=IdScheme.UNIVERSE)
    load = record_load(session, source_id, payload, request={"provider": provider, "month": month, "source_ref": source_ref},
                       as_of=_month_end(month))
    return None if load.unchanged else ingest_rows(session, load.load_id, _provider_rows(payload))


def _record_provider_load(rows: list[dict], *, provider: str, month: str, source_ref: str | None) -> None:
    with transaction() as session:
        report = record_esg_load(session, rows, provider=provider, month=month, source_ref=source_ref)
    if report and (report.unmatched_issuers or report.collisions):
        logger.warning("ESG %s %s: unmatched issuers %s, colliding codes %s",
                       provider, month, report.unmatched_issuers, report.collisions)


def ingest_esg_bytes(store, data: bytes, filename: str, *, provider: str, month: str, source_ref: str | None) -> EsgIntakeResult:
    """The one path for upload and API pull: bytes -> read_rows -> validate_esg -> ingest_esg."""
    mapping = load_esg_mapping(provider)
    try:
        raw = read_rows(data, filename, mapping)
    except ValueError as exc:
        record_file_load(store, LoadRecord(kind="esg", source_id=provider, month=month, status="failed", content_hash="",
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
