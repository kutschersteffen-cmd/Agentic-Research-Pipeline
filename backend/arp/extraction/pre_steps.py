"""The optional steps before extraction, run once per company inside an
extraction run: identity, content search, document management, parse &
index. Each is switched on per run (Settings.pre_*_enabled, set from the
node editor's StepSettings); with all of them off -- the default -- a
company goes straight to the per-item extraction as before.

They reuse the standalone pipelines' own pieces (identity resolution,
Document Discovery's homepage finder, crawler, downloader and change
detector), so a company prepared here is prepared exactly as those
screens would, and report what they found to the run's step view.

A step that fails -- it raised, or it produced nothing the next step can
use (an unclear identity, no homepage or report links, no documents,
nothing parsed) -- stops the company there: no extraction runs for it, and
an error report goes to the run's review queue (PreStepFailed, a
ReviewRequired) so a person decides, then restarts it from that step.
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
from arp.orchestration.batch_runner import ReviewRequired
from arp.orchestration.cost_tracker import combine_usage
from arp.orchestration.step_tally import record_cost, record_step
from arp.schemas.common import CompanyRef, now_iso
from arp.schemas.discovery import IdentityVerdict
from arp.storage.safe_path import safe_id

if TYPE_CHECKING:
    from arp.discovery.crawler import CandidateDocumentLink

logger = logging.getLogger(__name__)

LABELS = {"identity": "Identity", "content_search": "Content search", "document_mgmt": "Document management", "parse_index": "Parse & index"}


class PreStepFailed(ReviewRequired):
    """A step before extraction failed for one company, which stops there."""


class _Unusable(Exception):
    """The step ran but found nothing the next step can use."""

    def __init__(self, message: str, details: dict) -> None:
        super().__init__(message)
        self.details = details


async def prepare_company(
    company: CompanyRef, *, settings: Settings, llm: LLMClient, registry: DocumentSourceRegistry
) -> CompanyRef:
    """Runs the enabled steps in order and returns the company as the
    extraction should see it (identity may fill in its website and CIK).
    Raises PreStepFailed at the first step that fails."""
    candidates: list[CandidateDocumentLink] = []
    found: dict[str, dict] = {}
    if settings.pre_identity_enabled:
        company = await _run("identity", _identity(company, settings, llm), company, found)
    if settings.pre_content_search_enabled:
        company, candidates = await _run("content_search", _content_search(company, settings), company, found)
    if settings.pre_document_mgmt_enabled:
        await _run("document_mgmt", _document_mgmt(company, candidates, settings), company, found)
    if settings.pre_parse_index_enabled:
        await _run("parse_index", _parse_index(company, registry), company, found)
    return company


async def _run(node: str, step, company: CompanyRef, found: dict[str, dict]):
    """Runs one step and reports it to the step view. On failure, reports
    that too and stops the company with an error report for review."""
    started = time.monotonic()
    try:
        result, details = await step
    except _Unusable as exc:
        error, details = str(exc), {**exc.details, "failed": True, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - becomes the error report
        logger.exception("Pre-step %s failed for %s", node, company.company_id)
        error, details = f"{type(exc).__name__}: {exc}"[:500], {"failed": True, "error": f"{type(exc).__name__}: {exc}"[:500]}
    else:
        record_step(node, time.monotonic() - started, details)
        found[node] = details
        return result
    record_step(node, time.monotonic() - started, details)
    label = LABELS[node]
    raise PreStepFailed(
        f"{label} failed for {company.name}: {error}",
        {
            "company_id": company.company_id,
            "name": company.name,
            "ticker": company.ticker,
            "confidence": 0.0,  # sorts error reports to the top of the review queue
            "rationale": f"{label} failed: {error}. The company was stopped before extraction; "
            f"fix the cause, then restart it from {label} on the Extraction screen.",
            "failed_step": node,
            "failed_step_label": label,
            "error": error,
            "step_output": details,
            "found_before": found,
            "failed_at": now_iso(),
        },
    )


async def _identity(company: CompanyRef, settings: Settings, llm: LLMClient):
    from arp.discovery.identity_graph import resolve_company_identity
    from arp.discovery.site_finder import DuckDuckGoSearchClient
    from arp.ingestion.edgar import EdgarDocumentSource
    from arp.storage.identifier_map import IdentifierMapStore

    result, usages = await resolve_company_identity(
        company,
        llm=llm,
        edgar=EdgarDocumentSource(settings.edgar_user_agent, settings.cache_dir),
        search_client=DuckDuckGoSearchClient(settings.discovery_user_agent),
        max_search_results=settings.identity_resolution_max_search_results,
        confidence_threshold=settings.identity_resolution_confidence_threshold,
        identifier_map=IdentifierMapStore(settings.identifier_map_path),
    )
    if usages:
        record_cost(settings.llm_model, combine_usage(*usages))
    # Usable for fetching documents even when flagged: the flag feeds the identity review queue,
    # and entity confirmation (E63) still guards every fetched document.
    rule = result.match_rule
    usable = bool(result.resolved_cik or result.resolved_website) and (
        rule in ("exact_lei", "identifier_map", "supplied", "name_only")
        or (
            rule == "ambiguous"
            and result.verdict == IdentityVerdict.RESOLVED
            and result.confidence >= settings.identity_resolution_confidence_threshold
        )
    )
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
    if not usable:
        raise _Unusable(
            f"identity unclear (verdict {result.verdict.value}, confidence {result.confidence:.2f})"
            + (f": {result.rationale}" if getattr(result, "rationale", None) else ""),
            details,
        )
    return company, details


async def _content_search(company: CompanyRef, settings: Settings):
    from arp.discovery.crawler import CrawlConfig, HomepageUnreachableError, crawl_for_documents
    from arp.discovery.site_finder import DuckDuckGoSearchClient, resolve_company_homepage

    homepage = company.website or await resolve_company_homepage(company.name, DuckDuckGoSearchClient(settings.discovery_user_agent))
    if not homepage:
        raise _Unusable("no homepage found for the company", {"homepage": None, "links": 0, "found_homepage": False})
    config = CrawlConfig(
        user_agent=settings.discovery_user_agent,
        max_depth=settings.discovery_max_crawl_depth,
        max_pages=settings.discovery_max_pages_per_company,
        request_delay_seconds=settings.discovery_request_delay_seconds,
    )
    try:
        candidates = await crawl_for_documents(homepage, config)
    except HomepageUnreachableError as exc:
        raise _Unusable(f"homepage {homepage} could not be reached ({exc})"[:500], {"homepage": homepage, "links": 0, "found_homepage": True, "unreachable": True}) from exc
    if not candidates:
        raise _Unusable(f"no report links found on {homepage}", {"homepage": homepage, "links": 0, "found_homepage": True})
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
    from arp.discovery.refresh import refresh_hook
    from arp.ingestion.indexing_config import IndexingConfig
    from arp.storage.document_blob_store import blob_store_for

    downloaded, changed = [], 0
    if candidates:
        downloaded = await download_documents(
            company, candidates, settings.documents_dir, settings.discovery_user_agent,
            store=blob_store_for(IndexingConfig.from_settings(settings)), trigger="extraction_pre_step",
        )
        detector = ChangeDetector(
            state_dir=settings.discovery_state_dir,
            global_events_path=settings.documents_dir / "_events.jsonl",
            webhook_url=settings.discovery_webhook_url,
            on_events=refresh_hook(settings),
        )
        changed = len(await detector.diff_and_record(company, downloaded))
    folder = Path(settings.documents_dir) / safe_id(company.company_id, label="company_id")
    files = [f for f in folder.rglob("*") if f.is_file()] if folder.exists() else []
    details = {
        "downloaded": len(downloaded),
        "new_or_changed": changed,
        "documents": len(files),
        "bytes": sum(f.stat().st_size for f in files),
    }
    if not files:
        reason = f"none of the {len(candidates)} found links could be downloaded" if candidates else "no documents on file and nothing found to download"
        raise _Unusable(f"no documents for the company: {reason}", details)
    return None, details


async def _parse_index(company: CompanyRef, registry: DocumentSourceRegistry):
    """Fetches and parses every source's documents once -- the content store
    keeps the text, so each item's evidence step reads it back rather than
    parsing again -- and counts the chunks evidence will be ranked from."""
    docs = await registry.fetch_all(company)
    chunks = sum(len(chunk_document(d)) for d in docs)
    details = {"documents": len(docs), "chunks": chunks, "characters": sum(len(d.full_text or "") for d in docs)}
    if not chunks:
        raise _Unusable("no document text could be parsed" if docs else "no documents found in any source", details)
    return None, details
