"""Step 1's table: per company of a flow, what is already stored. Computed on every read, never stored."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from arp.api.auth import Principal
from arp.argus.companies import problem_of
from arp.argus.flows import ArgusFlow
from arp.db.models import Company, CompanyIdentifier
from arp.orchestration.review_queue import latest_decisions
from arp.review.items import list_open_items
from arp.schemas.common import RunManifest
from arp.schemas.review import field_item_key, period_key
from arp.storage.document_store import DocumentContentStore
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.run_store import RunStore
from arp.universe_workbench.availability import availability
from arp.universe_workbench.mapping import MasterIndex, map_company
from arp.xbrl_pipeline.store import XbrlStore

SHOWN_SCHEMES = ("LEI", "ISIN", "CIK", "USER", "TICKER")
# The import folder's type names (spec data rule 3), in that order; any other type reads `other`.
DOC_TYPE_WORDS = {
    "10-K": "annual", "sustainability_report": "sustainability", "DEF-14A": "proxy", "earnings_transcript": "transcript",
    "investor_presentation": "presentation", "transition_plan": "transition-plan",
}
_WORD_ORDER = [*DOC_TYPE_WORDS.values(), "other"]
_RUN_LABELS = {"financials": "Financials", "tnfd": "TNFD", "transition_plan": "Transition Plan"}


class PriorRun(BaseModel):
    label: str
    date: str
    approved: int
    waiting: int


class FlowRow(BaseModel):
    company_id: str
    central_id: UUID | None
    name: str
    identifiers: dict[str, list[str]]
    master_identifiers: dict[str, list[str]]
    sector: str | None
    country: str | None
    problem: str | None
    extracted_before: PriorRun | None
    documents: int
    document_types: list[str]


def run_label(m: RunManifest) -> str:
    """As the start page labels runs (frontend/src/lib/argusStart.ts)."""
    if m.run_type != "extraction":
        return _RUN_LABELS.get(m.run_type, m.run_type)
    name = m.params.get("schema_name") or "Extraction"
    version = re.search(r":v(\d+)$", str(m.params.get("schema_version") or ""))
    return f"{name} v{version.group(1)}" if version else name


def document_words(doc_types: list[str]) -> list[str]:
    words = {DOC_TYPE_WORDS.get(t, "other") for t in doc_types}
    return [w for w in _WORD_ORDER if w in words]


def _prior_runs(run_store: RunStore, last_runs: dict[str, str], principal: Principal) -> dict[str, PriorRun]:
    out: dict[str, PriorRun] = {}
    for run_id in set(last_runs.values()):
        m = run_store.load_manifest(run_id)
        if m is None:
            continue
        decisions = latest_decisions(run_store, run_id)
        open_items = list_open_items(run_store, principal, run_id=run_id)
        results = run_store.read_results(run_id)
        for cid in (c for c, r in last_runs.items() if r == run_id):
            approved = 0
            for row in (r for r in results if r.get("company_id") == cid):
                for f in row.get("fields", []):
                    d = decisions.get(field_item_key(row.get("issuer_key", ""), f["field_id"], period_key(f)))
                    if (d is None and f.get("route") == "auto_accept") or (d and d.get("decision") in ("approve", "edit", "correct")):
                        approved += 1
            waiting = sum(1 for i in open_items if i.payload.get("company_id") == cid)
            out[cid] = PriorRun(label=run_label(m), date=m.created_at[:10], approved=approved, waiting=waiting)
    return out


def flow_rows(
    flow: ArgusFlow, *, session: Session, run_store: RunStore, content_store: DocumentContentStore, xbrl_store: XbrlStore,
    idmap: IdentifierMapStore, principal: Principal, documents_dir: Path,
) -> list[FlowRow]:
    if not flow.companies:
        return []
    avail = availability(flow.companies, run_store=run_store, content_store=content_store, xbrl_store=xbrl_store,
                         documents_dir=documents_dir)
    prior = _prior_runs(run_store, {cid: a.extraction.last_run_id for cid, a in avail.items() if a.extraction.last_run_id}, principal)
    central = [c.entity_id for c in flow.companies if c.entity_id]
    rows_db = {c.id: c for c in session.scalars(select(Company).where(Company.id.in_(central)))}
    ids_db: dict[UUID, dict[str, list[str]]] = {}
    for cid, scheme, value in session.execute(select(CompanyIdentifier.company_id, CompanyIdentifier.scheme, CompanyIdentifier.value).where(
            CompanyIdentifier.company_id.in_(central), CompanyIdentifier.valid_to.is_(None), CompanyIdentifier.scheme.in_(SHOWN_SCHEMES))):
        ids_db.setdefault(cid, {}).setdefault(scheme, []).append(value)
    index = MasterIndex.build(idmap)
    out = []
    for c in flow.companies:
        db = rows_db.get(c.entity_id)
        own = {s: [v] for s, v in (("LEI", c.lei), ("ISIN", c.isin), ("CIK", c.cik), ("TICKER", c.ticker)) if v}
        docs = avail[c.company_id].documents
        out.append(FlowRow(
            company_id=c.company_id, central_id=c.entity_id, name=c.name,
            identifiers={**ids_db.get(c.entity_id, {}), **own},  # the values as the list gave them win
            master_identifiers=map_company(c, index).identifiers,
            sector=(db and db.sector) or c.sector, country=(db and db.country) or c.country,
            problem=problem_of(c), extracted_before=prior.get(c.company_id),
            documents=docs.registered, document_types=document_words(docs.doc_types),
        ))
    return out
