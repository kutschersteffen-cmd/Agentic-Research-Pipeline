from __future__ import annotations

from pathlib import Path
from typing import Literal

from arp.ingestion.xbrl import _ANNUAL_FORMS, _full_year
from arp.xbrl_pipeline.models import CompanyFiles, FactRow, FactView, PivotRow, PivotTable
from arp.xbrl_pipeline.store import XbrlStore

_SORTS = {
    "period_end": lambda r: r.period_end,
    "filed": lambda r: r.filed or "",
    "value": lambda r: r.value,
    "concept": lambda r: r.tag_id,
    "form": lambda r: r.form,
}


def is_annual(row: FactRow) -> bool:
    return ((row.form in _ANNUAL_FORMS or row.form == "ESEF") and row.fiscal_period == "FY"
            and _full_year({"start": row.period_start, "end": row.period_end}))


def _year(row: FactRow) -> int:
    # Calendar year of period_end: companyfacts' fy labels comparatives with the filing's year.
    return int(row.period_end[:4])


def list_company_files(store: XbrlStore, *, offset: int = 0, limit: int = 50) -> tuple[list[CompanyFiles], int]:
    items = []
    for cik10 in store.ciks():
        meta = store.meta(cik10) or {}
        original = store.file_path(cik10, "original")
        items.append(CompanyFiles(
            cik=cik10,
            company_id=meta.get("company_id", ""),
            name=meta.get("company_name"),
            fetched_at=meta.get("fetched_at", ""),
            fact_count=meta.get("fact_count", 0),
            tags=meta.get("tags"),
            original_size=original.stat().st_size if original else 0,
            report=store.report_meta(cik10),
            market=meta.get("market", "sec"),
        ))
    items.sort(key=lambda f: f.fetched_at, reverse=True)
    return items[offset:offset + limit], len(items)


def _labels(store: XbrlStore, cik10: str) -> dict[str, str | None]:
    return {f"{c.taxonomy}:{c.concept}": c.label for c in store.read_catalog(cik10)}


def _matches(row: FactRow, label: str | None, q: str, taxonomy: str | None) -> bool:
    if taxonomy and row.taxonomy != taxonomy:
        return False
    return not q or q in row.tag_id.lower() or q in (label or "").lower()


def query_facts(
    store: XbrlStore,
    cik10: str,
    *,
    q: str = "",
    taxonomy: str | None = None,
    form: str | None = None,
    period_year: int | None = None,
    annual_only: bool = False,
    sort: str = "period_end",
    order: Literal["asc", "desc"] = "desc",
    offset: int = 0,
    limit: int = 100,
) -> tuple[list[FactView], int]:
    if sort not in _SORTS:
        raise ValueError(f"unknown sort key: {sort}")
    q = q.lower()
    labels = _labels(store, cik10)
    # ponytail: loads the company's facts.jsonl per request, cache by mtime if large filers feel slow
    hits = [
        FactView(**r.model_dump(), label=labels.get(r.tag_id))
        for r in store.read_facts(cik10)
        if _matches(r, labels.get(r.tag_id), q, taxonomy)
        and (form is None or r.form == form)
        and (period_year is None or _year(r) == period_year)
        and (not annual_only or is_annual(r))
    ]
    hits.sort(key=_SORTS[sort], reverse=order == "desc")
    return hits[offset:offset + limit], len(hits)


def pivot_facts(
    store: XbrlStore, cik10: str, *, q: str = "", taxonomy: str | None = None, offset: int = 0, limit: int = 100
) -> PivotTable:
    q = q.lower()
    labels = _labels(store, cik10)
    best: dict[tuple[str, str], dict[int, FactRow]] = {}
    for r in store.read_facts(cik10):
        if not is_annual(r) or not _matches(r, labels.get(r.tag_id), q, taxonomy):
            continue
        cell = best.setdefault((r.tag_id, r.unit), {})
        year = _year(r)
        if year not in cell or (r.filed or "") >= (cell[year].filed or ""):
            cell[year] = r
    years = sorted({y for cell in best.values() for y in cell}, reverse=True)
    keys = sorted(best)
    rows = [
        PivotRow(tag_id=tag_id, label=labels.get(tag_id), unit=unit,
                 values={y: best[(tag_id, unit)][y].value if y in best[(tag_id, unit)] else None for y in years})
        for tag_id, unit in keys[offset:offset + limit]
    ]
    return PivotTable(years=years, rows=rows, total=len(keys))


def download_path(store: XbrlStore, cik10: str, kind: str) -> Path:
    path = store.file_path(cik10, kind)  # KeyError for an unknown kind
    if path is None:
        raise FileNotFoundError(kind)
    path = path.resolve()
    if not path.is_relative_to(store.company_dir(cik10).resolve()):
        raise FileNotFoundError(kind)
    return path
