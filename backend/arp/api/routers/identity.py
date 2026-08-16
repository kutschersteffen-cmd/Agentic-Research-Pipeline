from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arp.api.deps import get_edgar_source, get_llm_client, get_run_store, get_web_search_client, settings_dep
from arp.config import Settings
from arp.discovery.identity_pipeline import create_identity_run, enriched_universe, execute_identity_run
from arp.discovery.site_finder import WebSearchClient
from arp.ingestion.edgar import EdgarDocumentSource
from arp.orchestration.review_queue import latest_decisions, record_review_decision
from arp.schemas.common import CompanyRef
from arp.storage.run_store import RunStore
from arp.universe import load_company_universe

router = APIRouter(prefix="/api/identity", tags=["identity"])


class IdentityRunRequest(BaseModel):
    companies: list[CompanyRef] | None = None
    universe_path: str | None = None


@router.post("/runs")
async def start_identity_run(
    req: IdentityRunRequest,
    settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(get_run_store),
    edgar: EdgarDocumentSource = Depends(get_edgar_source),
    search_client: WebSearchClient = Depends(get_web_search_client),
) -> dict:
    """Resolves real-world identity (website/CIK) for a list of company
    names -- a separate enrichment run from document discovery. See
    arp/discovery/identity_pipeline.py's docstring for why this is kept
    separate: the LLM cost of resolving a company is paid once, ever, not
    once per discovery run. Feed the result of GET .../enriched-universe
    into the *existing* POST /api/discovery/runs as an ordinary universe.
    """
    companies = req.companies or (load_company_universe(req.universe_path) if req.universe_path else None)
    if not companies:
        raise HTTPException(400, "Provide either `companies` or `universe_path`.")

    llm = get_llm_client()  # raises a clear error before a run manifest is even created
    run_id = create_identity_run(companies, run_store)

    async def _background() -> None:
        await execute_identity_run(
            run_id, companies, llm=llm, settings=settings, run_store=run_store, edgar=edgar, search_client=search_client
        )

    asyncio.create_task(_background())
    return {"run_id": run_id, "company_count": len(companies)}


@router.get("/runs/{run_id}")
def get_identity_run(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    return manifest.model_dump(mode="json")


@router.get("/runs/{run_id}/results")
def get_identity_results(
    run_id: str, offset: int = 0, limit: int = 200, run_store: RunStore = Depends(get_run_store)
) -> dict:
    rows = run_store.read_jsonl(run_store.results_path(run_id))
    return {"total": len(rows), "results": rows[offset : offset + limit]}


@router.get("/runs/{run_id}/review-queue")
def get_identity_review_queue(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    rows = run_store.read_jsonl(run_store.review_queue_path(run_id))
    decisions = latest_decisions(run_store, run_id)
    pending = [r for r in rows if r["item_key"] not in decisions]
    return {"pending": pending, "decided": [{"item": r, "decision": decisions[r["item_key"]]} for r in rows if r["item_key"] in decisions]}


class ReviewDecisionRequest(BaseModel):
    item_key: str
    decision: str  # approve | edit | reject
    reviewer: str | None = None
    edited_value: dict | None = None


@router.post("/runs/{run_id}/review")
def submit_identity_review(
    run_id: str, req: ReviewDecisionRequest, run_store: RunStore = Depends(get_run_store)
) -> dict:
    """decision='edit' with edited_value={"resolved_website": ..., "resolved_cik": ...}
    is how a reviewer corrects an uncertain/unresolved match -- picked up
    by GET .../enriched-universe below."""
    record_review_decision(run_store, run_id, req.item_key, req.decision, req.reviewer, req.edited_value)
    return {"status": "recorded"}


@router.get("/runs/{run_id}/enriched-universe")
def get_enriched_universe(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    """The point of this run type: a normal company universe (website/cik
    filled in), merging resolved-and-clean companies with anything a human
    approved/edited in the review queue. Feed straight into
    POST /api/discovery/runs as `companies`."""
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    companies = enriched_universe(run_store, run_id)
    return {"companies": [c.model_dump(mode="json") for c in companies]}
