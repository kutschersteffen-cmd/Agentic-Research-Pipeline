"""The optional steps before extraction, run once per company inside an
extraction run: identity, content search, document management, parse &
index. Each is switched on per run (Settings.pre_*_enabled, set from the
node editor's StepSettings); with all of them off -- the default -- a
company goes straight to the per-item extraction as before.

They reuse the standalone pipelines' own pieces (identity resolution,
Document Discovery's homepage finder, crawler, downloader and change
detector), so a company prepared here is prepared exactly as those
screens would, and report what they found to the run's step view.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from arp.config import Settings
from arp.ingestion.parsing import chunk_document
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient
from arp.orchestration.cost_tracker import combine_usage
from arp.orchestration.step_tally import record_cost, record_step
from arp.schemas.common import CompanyRef
from arp.schemas.discovery import IdentityVerdict
from arp.storage.safe_path import safe_id

if TYPE_CHECKING:
    from arp.discovery.crawler import CandidateDocumentLink

logger = logging.getLogger(__name__)



async def prepare_company(
    company: CompanyRef, *, settings: Settings, llm: LLMClient, registry: DocumentSourceRegistry
) -> CompanyRef:
    """Runs the enabled steps in order and returns the company as the
    extraction should see it (identity may fill in its website and CIK).
    A step that fails is recorded and the company moves on: what the
    extraction finds on its own is still worth having."""
    candidates: list[CandidateDocumentLink] = []
    if settings.pre_identity_enabled:
        company = await _timed("identity", _identity(company, settings, llm), fallback=company)
    if settings.pre_content_search_enabled:
        company, candidates = await _timed("content_search", _content_search(company, settings), fallback=(company, []))
    if settings.pre_document_mgmt_enabled:
        await _timed("document_mgmt", _document_mgmt(company, candidates, settings), fallback=None)
    if settings.pre_parse_index_enabled:
        await _timed("parse_index", _parse_index(company, registry), fallback=None)
    return company


async def _timed(node: str, step, *, fallback):
    """Runs one step and reports it; a failure is reported too and yields
    `fallback`, so the company carries on as if the step were off."""
    started = time.monotonic()
    try:
        result, details = await step
    except Exception as exc:  # noqa: BLE001 - one step failing must not cost the company its extraction
        logger.exception("Pre-step %s failed", node)
        record_step(node, time.monotonic() - started, {"failed": True, "error": str(exc)[:300]})
        return fallback
    record_step(node, time.monotonic() - started, details)
    return result


async def _identity(company: CompanyRef, settings: Settings, llm: LLMClient):
    from arp.discovery.identity_graph import resolve_company_identity
    from arp.discovery.site_finder import DuckDuckGoSearchClient
    from arp.ingestion.edgar import EdgarDocumentSource

    result, usages = await resolve_company_identity(
        company,
        llm=llm,
        edgar=EdgarDocumentSource(settings.edgar_user_agent, settings.cache_dir),
        search_client=DuckDuckGoSearchClient(settings.discovery_user_agent),
        max_search_results=settings.identity_resolution_max_search_results,
        confidence_threshold=settings.identity_resolution_confidence_threshold,
    )
    if usages:
        record_cost(settings.llm_model, combine_usage(*usages))
    usable = result.verdict == IdentityVerdict.RESOLVED and not result.flagged_for_review
    if usable:
        company = company.model_copy(
            update={"website": company.website or result.resolved_website, "cik": company.cik or result.resolved_cik}
        )
    details = {
        "verdict": result.verdict.value,
        "resolved": usable,
        "flagged": result.flagged_for_review,
        "website": result.resolved_website,
        "cik": result.resolved_cik,
        "confidence": round(result.confidence, 2),
    }
    return company, details


async def _content_search(company: CompanyRef, settings: Settings):
    from arp.discovery.crawler import CrawlConfig, HomepageUnreachableError, crawl_for_documents
    from arp.discovery.site_finder import DuckDuckGoSearchClient, resolve_company_homepage

    homepage = company.website or await resolve_company_homepage(company.name, DuckDuckGoSearchClient(settings.discovery_user_agent))
    if not homepage:
        return (company, []), {"homepage": None, "links": 0, "found_homepage": False}
    config = CrawlConfig(
        user_agent=settings.discovery_user_agent,
        max_depth=settings.discovery_max_crawl_depth,
        max_pages=settings.discovery_max_pages_per_company,
        request_delay_seconds=settings.discovery_request_delay_seconds,
    )
    try:
        candidates = await crawl_for_documents(homepage, config)
    except HomepageUnreachableError as exc:
        return (company, []), {"homepage": homepage, "links": 0, "found_homepage": True, "unreachable": True, "error": str(exc)[:300]}
    return (company.model_copy(update={"website": homepage}), candidates), {
        "homepage": homepage,
        "links": len(candidates),
        "found_homepage": True,
        "urls": [c.url for c in candidates[:20]],
    }


async def _document_mgmt(company: CompanyRef, candidates: list[CandidateDocumentLink], settings: Settings):
    """Downloads what content search found (nothing to download when it is
    off), records new and changed documents, and takes stock of every
    document the company now has on disk."""
    from arp.discovery.change_detector import ChangeDetector
    from arp.discovery.downloader import download_documents

    downloaded, changed = [], 0
    if candidates:
        downloaded = await download_documents(company, candidates, settings.documents_dir, settings.discovery_user_agent)
        detector = ChangeDetector(
            state_dir=settings.discovery_state_dir,
            global_events_path=settings.documents_dir / "_events.jsonl",
            webhook_url=settings.discovery_webhook_url,
        )
        changed = len(await detector.diff_and_record(company, downloaded))
    folder = Path(settings.documents_dir) / safe_id(company.company_id, label="company_id")
    files = [f for f in folder.rglob("*") if f.is_file()] if folder.exists() else []
    return None, {
        "downloaded": len(downloaded),
        "new_or_changed": changed,
        "documents": len(files),
        "bytes": sum(f.stat().st_size for f in files),
    }


async def _parse_index(company: CompanyRef, registry: DocumentSourceRegistry):
    """Fetches and parses every source's documents once -- the content store
    keeps the text, so each item's evidence step reads it back rather than
    parsing again -- and counts the chunks evidence will be ranked from."""
    docs = await registry.fetch_all(company)
    chunks = sum(len(chunk_document(d)) for d in docs)
    return None, {"documents": len(docs), "chunks": chunks, "characters": sum(len(d.full_text or "") for d in docs)}
