"""Read-only company match and stored data for a stock; nothing here writes `companies` or `company_identifiers`."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arp.db.companies import lookup
from arp.db.company_view import facts as company_facts
from arp.db.models import Company, IdScheme
from arp.research.indirect_exposure.nace import nace_sectors
from arp.research.revenue_exposure.catalogue import _TOTAL_LABELS, by_company, load_catalogue, total_value
from arp.research.stock_inference.schemas import InferStock
from arp.schemas.revenue_exposure import CatalogueDataPoint

_PAGE = 100


def match_company(session: Session, stock: InferStock) -> UUID | None:
    for scheme, value in ((IdScheme.ISIN, stock.isin), (IdScheme.LEI, stock.lei), (IdScheme.CIK, stock.cik)):
        if value and (found := lookup(session, scheme, value)):
            return found
    ids = session.scalars(select(Company.id).where(func.lower(Company.name) == stock.name.strip().lower()).limit(2)).all()
    return ids[0] if len(ids) == 1 else None


def load_segments(path: Path) -> dict[str, list[CatalogueDataPoint]]:
    return by_company(load_catalogue(path))


def _latest_per_field(session: Session, company_id: UUID) -> list[dict]:
    best: dict[str, dict] = {}
    offset = 0
    while page := company_facts(session, company_id, limit=_PAGE, offset=offset):
        for f in page:
            cur = best.get(f.field_id)
            if cur is None or (f.period_end or date.min) > (cur["period_end"] or date.min):
                best[f.field_id] = {"field_id": f.field_id, "period_end": f.period_end, "value": f.value, "unit": f.unit}
        offset += _PAGE
    return [{**v, "period_end": v["period_end"].isoformat() if v["period_end"] else None} for v in best.values()]


def _segment_rows(rows: list[CatalogueDataPoint]) -> list[dict]:
    out = []
    for r in rows:
        if r.label == _TOTAL_LABELS[r.metric]:
            continue
        total = total_value(rows, r.metric)
        share = r.as_pct_of_total if r.as_pct_of_total is not None else (
            r.value / total if r.value is not None and total else None)
        out.append({"label": r.label, "metric": str(r.metric), "value": r.value, "unit": r.unit, "period": r.period,
                    "share": share})
    return out


def stored_data(
    session: Session | None, stock: InferStock, company_id: UUID | None, segments: dict[str, list[CatalogueDataPoint]]
) -> dict:
    codes = dict(stock.codes)
    facts: list[dict] = []
    if company_id is not None:
        company = session.get(Company, company_id)
        for key, val in (("isic_code", company.isic_code), ("sector", company.sector)):
            if val:
                codes.setdefault(key, val)
        facts = _latest_per_field(session, company_id)
    exiobase: set[str] = set()
    for key, code in stock.codes.items():
        if key.lower().startswith("nace"):
            exiobase |= nace_sectors(code, "2.1" if "2.1" in key else "2")
    return {"codes": codes, "exiobase": sorted(exiobase), "facts": facts,
            "segments": _segment_rows(segments.get(stock.company_id, []))}
