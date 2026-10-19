from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

import httpx

from arp.config import Settings
from arp.discovery.change_detector import ChangeDetector
from arp.discovery.crawler import CrawlConfig, HomepageUnreachableError, crawl_for_documents
from arp.discovery.downloader import download_documents
from arp.discovery.refresh import refresh_hook
from arp.discovery.site_check import check_homepage
from arp.discovery.site_finder import DuckDuckGoSearchClient, WebSearchClient, homepage_from_ids, resolve_company_homepage
from arp.ingestion.edgar import EdgarDocumentSource
from arp.ingestion.esef import EsefDocumentSource
from arp.ingestion.indexing_config import IndexingConfig
from arp.orchestration.batch_runner import run_batch, run_sinks
from arp.orchestration.job_manager import JobManager
from arp.orchestration.jobs import hold_run
from arp.schemas.common import CompanyRef, DocType
from arp.schemas.discovery import DiscoveredDocument, DiscoveryCompanyResult, DiscoveryRunParams
from arp.storage.document_blob_store import blob_store_for
from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)


async def _discover_for_company(
    company: CompanyRef,
    *,
    settings: Settings,
    search_client: WebSearchClient,
    change_detector: ChangeDetector,
    doc_types: list[DocType] | None,
    edgar: EdgarDocumentSource | None = None,
    esef: EsefDocumentSource | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    today: date | None = None,
    sleep=asyncio.sleep,
) -> DiscoveryCompanyResult:
    today = today or date.today()
    filings = await _edgar_filings(company, edgar, doc_types) if edgar and company.cik else []
    esef_docs, _esef_current = await _esef_documents(company, esef, doc_types, today) if esef else ([], False)
    homepage, check = company.website, None
    if not homepage:  # a supplied website is used unchecked; a derived one is checked first
        homepage = await homepage_from_ids(
            settings.discovery_user_agent, lei=company.lei, isin=company.isin, cik=company.cik, transport=transport
        )
        from_ids = homepage is not None  # search runs only without a Wikidata hit, and never gets the flag
        homepage = homepage or await resolve_company_homepage(company.name, search_client)
        if homepage:
            check = await check_homepage(
                homepage, company, settings.discovery_user_agent, identifier_source=from_ids, transport=transport
            )
            if check.verdict == "rejected":
                homepage = None

    candidates, unreachable, crawl_error = [], False, None
    if homepage:
        crawl_config = CrawlConfig(
            user_agent=settings.discovery_user_agent,
            max_depth=settings.discovery_max_crawl_depth,
            max_pages=settings.discovery_max_pages_per_company,
            request_delay_seconds=settings.discovery_request_delay_seconds,
            expected_year=today.year - 1,
        )
        try:
            candidates = await crawl_for_documents(homepage, crawl_config, transport=transport, sleep=sleep)
        except HomepageUnreachableError as exc:
            unreachable, crawl_error = True, str(exc)
    if doc_types:
        candidates = [c for c in candidates if c.doc_type in doc_types]

    downloaded = await download_documents(
        company, candidates, settings.documents_dir, settings.discovery_user_agent,
        store=blob_store_for(IndexingConfig.from_settings(settings)), trigger="discovery", transport=transport,
        known=change_detector.known_documents(company.company_id),
    ) if candidates else []
    events = await change_detector.diff_and_record(company, esef_docs + downloaded)

    return DiscoveryCompanyResult(
        company_id=company.company_id,
        name=company.name,
        homepage_used=homepage,
        homepage_check=check,
        homepage_unreachable=unreachable,
        crawl_error=crawl_error,
        documents_found=filings + esef_docs + downloaded,
        new_events=events,
    )


# An ESEF filing whose period ended within this many days (18 months) counts as the current annual report.
_ESEF_CURRENT_DAYS = 548


async def _esef_documents(
    company: CompanyRef, source: EsefDocumentSource, doc_types: list[DocType] | None, today: date
) -> tuple[list[DiscoveredDocument], bool]:
    """The company's latest ESEF filing, registered like any ingested document, and whether it is current.
    Best-effort: an index outage or a bad package leaves the homepage crawl to find what it can."""
    try:
        docs = await source.fetch(company, doc_types)
    except Exception as exc:  # noqa: BLE001 -- a failed ESEF call must not fail the company
        logger.warning("ESEF fetch failed for %s: %s", company.company_id, exc)
        return [], False
    found = [
        DiscoveredDocument(company_id=company.company_id, doc_type=d.doc_type, url=d.source_url,
                           local_path=d.local_path, sha256=d.content_key or d.sha256)
        for d in docs if d.source_url
    ]
    try:
        current = any(date.fromisoformat(d.fiscal_period[:10]) >= today - timedelta(days=_ESEF_CURRENT_DAYS) for d in docs)
    except (ValueError, TypeError):  # a missing or malformed period_end is not current
        current = False
    return found, current


async def _edgar_filings(company: CompanyRef, edgar: EdgarDocumentSource, doc_types: list[DocType] | None) -> list[DiscoveredDocument]:
    """The company's latest SEC filings, fetched and registered like any ingested document.
    Best-effort: an EDGAR outage leaves the homepage crawl to find what it can."""
    try:
        docs = await edgar.fetch(company, doc_types)
    except Exception as exc:  # noqa: BLE001 -- a failed EDGAR call must not fail the company
        logger.warning("EDGAR fetch failed for %s: %s", company.company_id, exc)
        return []
    return [DiscoveredDocument(company_id=company.company_id, doc_type=d.doc_type, url=d.source_url or "", sha256=d.sha256) for d in docs]


def create_discovery_run(
    companies: list[CompanyRef], doc_types: list[DocType] | None, triggered_by: str, run_store: RunStore
) -> str:
    job_manager = JobManager(run_store)
    params = DiscoveryRunParams(
        universe_source=f"{len(companies)} companies", doc_types=doc_types or [], triggered_by=triggered_by
    )
    manifest = job_manager.create_run("discovery", params.model_dump(mode="json"), len(companies), companies=companies)
    return manifest.run_id


async def execute_discovery_run(
    run_id: str,
    companies: list[CompanyRef],
    *,
    settings: Settings,
    run_store: RunStore,
    doc_types: list[DocType] | None = None,
    search_client: WebSearchClient | None = None,
    esef_source: EsefDocumentSource | None = None,
    edgar_source: EdgarDocumentSource | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    today: date | None = None,
    sleep=None,
) -> str:
    """Runs the document discovery pipeline over a company universe against
    an already-created run (see create_discovery_run).

    Shared by the manual API/CLI trigger and the periodic scheduler so both
    paths behave identically. Resumable and checkpointed via run_batch;
    every new/updated document raises a DocumentEvent through
    ChangeDetector (internal feed + optional webhook + event-driven
    refresh). With `esef_enabled`, each company with an LEI first gets its
    latest ESEF filing (`esef_source`, else one from settings), recorded
    like any discovered document.
    """
    job_manager = JobManager(run_store)
    search_client = search_client or DuckDuckGoSearchClient(settings.discovery_user_agent, transport=transport)
    change_detector = ChangeDetector(
        state_dir=settings.discovery_state_dir,
        global_events_path=settings.documents_dir / "_events.jsonl",
        webhook_url=settings.discovery_webhook_url,
        on_events=refresh_hook(settings, run_store),
    )
    if edgar_source is None:
        from arp.retrieval.content_store_factory import content_store_for

        edgar_source = EdgarDocumentSource(
            settings.edgar_user_agent, settings.cache_dir, content_store=content_store_for(settings),
            submissions_ttl_hours=settings.edgar_submissions_ttl_hours, indexing_config=IndexingConfig.from_settings(settings),
        )
    if settings.esef_enabled:
        esef_source = esef_source or EsefDocumentSource(settings.esef_index_url, settings.cache_dir, transport=transport)
    else:
        esef_source = None

    async def _worker(company: CompanyRef) -> DiscoveryCompanyResult:
        return await _discover_for_company(
            company, settings=settings, search_client=search_client, change_detector=change_detector, doc_types=doc_types,
            edgar=edgar_source, esef=esef_source, transport=transport, today=today, sleep=sleep or asyncio.sleep,
        )

    def _on_success(company: CompanyRef, result: DiscoveryCompanyResult) -> None:
        # no documents, or a PDF that doesn't name the company (doc_check), needs a reviewer
        flagged = any(d.company_match in ("none", "no_text") for d in result.documents_found)
        job_manager.record_progress(
            run_id,
            completed_delta=1,
            review_delta=1 if not result.documents_found or flagged else 0,
        )

    def _on_error(company: CompanyRef, exc: Exception) -> None:
        job_manager.record_progress(run_id, failed_delta=1)

    with hold_run(run_store, run_id):  # one worker per run; RunBusy if another holds it
        await run_batch(
            companies,
            item_key=lambda c: c.company_id,
            worker=_worker,
            sinks=run_sinks(run_store, run_id),
            concurrency=settings.max_concurrent_downloads,
            result_to_json=lambda r: r.model_dump(mode="json"),
            on_success=_on_success,
            on_error=_on_error,
        )

        job_manager.finish_run(run_id)
    return run_id


async def run_discovery(
    companies: list[CompanyRef],
    *,
    settings: Settings,
    run_store: RunStore,
    doc_types: list[DocType] | None = None,
    triggered_by: str = "manual",
    search_client: WebSearchClient | None = None,
) -> str:
    """Convenience wrapper (create + execute in one call) for synchronous
    callers such as the CLI and the scheduler."""
    run_id = create_discovery_run(companies, doc_types, triggered_by, run_store)
    return await execute_discovery_run(
        run_id, companies, settings=settings, run_store=run_store, doc_types=doc_types, search_client=search_client
    )
