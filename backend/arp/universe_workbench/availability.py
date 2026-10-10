"""What the tool already stores per company. Read-only; each store is scanned once per call."""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from arp.schemas.common import CompanyRef
from arp.storage.document_store import DocumentContentStore, files_on_disk
from arp.storage.run_store import RunStore
from arp.xbrl_pipeline.store import XbrlStore

EXTRACTION_RUN_TYPES = ("extraction", "financials", "tnfd", "transition_plan")


class IdentityAvail(BaseModel):
    run_id: str
    verdict: str
    resolved_cik: str | None = None
    resolved_website: str | None = None


class DocumentsAvail(BaseModel):
    registered: int = 0
    parsed: int = 0
    on_disk: int = 0
    doc_types: list[str] = []
    last_seen_at: str | None = None


class ExtractionAvail(BaseModel):
    runs: int = 0
    run_types: list[str] = []
    last_run_id: str | None = None
    last_run_at: str | None = None


class XbrlAvail(BaseModel):
    key: str
    market: str
    fact_count: int
    fetched_at: str
    report: bool


class Availability(BaseModel):
    identity: IdentityAvail | None
    documents: DocumentsAvail
    extraction: ExtractionAvail
    xbrl: XbrlAvail | None


def _newest_first(run_store: RunStore, run_type: str):
    # Run ids are random, so order by created_at rather than trusting the directory order.
    return sorted(run_store.list_runs(run_type), key=lambda m: m.created_at, reverse=True)


def availability(
    companies: list[CompanyRef],
    *,
    run_store: RunStore,
    content_store: DocumentContentStore,
    xbrl_store: XbrlStore,
    documents_dir: Path,
) -> dict[str, Availability]:
    ids = list(dict.fromkeys(c.company_id for c in companies))
    wanted = set(ids)

    # ponytail: full scan of identity runs; add a company_id -> latest result index if runs pile up.
    identity: dict[str, IdentityAvail] = {}
    for m in _newest_first(run_store, "identity"):
        for row in run_store.read_jsonl(run_store.results_path(m.run_id)):
            cid = row.get("company_id")
            if cid in wanted and cid not in identity:
                identity[cid] = IdentityAvail(
                    run_id=m.run_id, verdict=str(row.get("verdict", "")),
                    resolved_cik=row.get("resolved_cik"), resolved_website=row.get("resolved_website"))

    # ponytail: full scan of extraction-like runs; add a company_id -> runs index if runs pile up.
    runs = sorted((m for t in EXTRACTION_RUN_TYPES for m in run_store.list_runs(t)),
                  key=lambda m: m.created_at, reverse=True)
    extraction: dict[str, ExtractionAvail] = {}
    for m in runs:
        in_run = {r.get("company_id") for r in run_store.read_jsonl(run_store.results_path(m.run_id))} & wanted
        for cid in in_run:
            e = extraction.setdefault(cid, ExtractionAvail())
            if e.last_run_id is None:  # newest run first
                e.last_run_id, e.last_run_at = m.run_id, m.created_at
            e.runs += 1
            if m.run_type not in e.run_types:
                e.run_types = sorted([*e.run_types, m.run_type])

    # ponytail: reads every meta.json; add a company_id -> key index file if the XBRL store grows.
    xbrl: dict[str, XbrlAvail] = {}
    for key in xbrl_store.ciks():
        meta = xbrl_store.meta(key) or {}
        item = None
        for cid in xbrl_store.company_ids(key):
            if cid in wanted and cid not in xbrl:
                item = item or XbrlAvail(
                    key=key, market=meta.get("market") or "sec", fact_count=int(meta.get("fact_count") or 0),
                    fetched_at=meta.get("fetched_at") or "", report=xbrl_store.report_meta(key) is not None)
                xbrl[cid] = item

    stored = content_store.readiness_by_company(ids)
    return {
        cid: Availability(
            identity=identity.get(cid),
            documents=DocumentsAvail(**{**stored.get(cid, {}), "on_disk": files_on_disk(documents_dir, cid)}),
            extraction=extraction.get(cid, ExtractionAvail()),
            xbrl=xbrl.get(cid),
        )
        for cid in ids
    }
