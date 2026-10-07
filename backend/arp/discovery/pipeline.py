from __future__ import annotations

import logging

from arp.config import Settings
from arp.discovery.change_detector import ChangeDetector, poll_esef_filings
from arp.discovery.crawler import CrawlConfig, HomepageUnreachableError, crawl_for_documents
from arp.discovery.downloader import download_documents
from arp.discovery.refresh import refresh_hook
from arp.discovery.site_finder import DuckDuckGoSearchClient, WebSearchClient, homepage_from_cik, resolve_company_homepage
from arp.ingestion.edgar import EdgarDocumentSource
from arp.ingestion.esef import EsefDocumentSource
from arp.ingestion.indexing_config import IndexingConfig
from arp.orchestration.batch_runner import run_batch
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
) -> DiscoveryCompanyResult:
    filings = await _edgar_filings(company, edgar, doc_types) if edgar and company.cik else []
    homepage = company.website or await homepage_from_cik(settings.discovery_user_agent, company.cik)
    if not homepage:
        homepage = await resolve_company_homepage(company.name, search_client)
    if not homepage:
        return DiscoveryCompanyResult(company_id=company.company_id, name=company.name, homepage_used=None, documents_found=filings)

    crawl_config = CrawlConfig(
        user_agent=settings.discovery_user_agent,
        max_depth=settings.discovery_max_crawl_depth,
        max_pages=settings.discovery_max_pages_per_company,
        request_delay_seconds=settings.discovery_request_delay_seconds,
    )
    try:
        candidates = await crawl_for_documents(homepage, crawl_config)
    except HomepageUnreachableError as exc:
        return DiscoveryCompanyResult(company_id=company.company_id, name=company.name, homepage_used=homepage, homepage_unreachable=True, crawl_error=str(exc), documents_found=filings)
    if doc_types:
        candidates = [c for c in candidates if c.doc_type in doc_types]

    downloaded = await download_documents(
        company, candidates, settings.documents_dir, settings.discovery_user_agent,
        store=blob_store_for(IndexingConfig.from_settings(settings)), trigger="discovery",
    )
    events = await change_detector.diff_and_record(company, downloaded)

    return DiscoveryCompanyResult(
        company_id=company.company_id,
        name=company.name,
        homepage_used=homepage,
        documents_found=filings + downloaded,
        new_events=events,
    )


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
) -> str:
    """Runs the document discovery pipeline over a company universe against
    an already-created run (see create_discovery_run).

    Shared by the manual API/CLI trigger and the periodic scheduler so both
    paths behave identically. Resumable and checkpointed via run_batch;
    every new/updated document raises a DocumentEvent through
    ChangeDetector (internal feed + optional webhook + event-driven
    refresh). With `esef_enabled`, each company with an LEI is also polled
    for its latest ESEF filing (`esef_source`, else one from settings).
    """
    job_manager = JobManager(run_store)
    search_client = search_client or DuckDuckGoSearchClient(settings.discovery_user_agent)
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
        esef_source = esef_source or EsefDocumentSource(settings.esef_index_url, settings.cache_dir)
    else:
        esef_source = None

    async def _worker(company: CompanyRef) -> DiscoveryCompanyResult:
        result = await _discover_for_company(
            company, settings=settings, search_client=search_client, change_detector=change_detector, doc_types=doc_types,
            edgar=edgar_source,
        )
        if esef_source is not None:
            events = await poll_esef_filings(company, esef_source, change_detector, doc_types)
            result.new_events += events
        return result

    def _on_success(company: CompanyRef, result: DiscoveryCompanyResult) -> None:
        job_manager.record_progress(
            run_id,
            completed_delta=1,
            review_delta=0 if result.documents_found else 1,
        )

    def _on_error(company: CompanyRef, exc: Exception) -> None:
        job_manager.record_progress(run_id, failed_delta=1)

    with hold_run(run_store, run_id):  # one worker per run; RunBusy if another holds it
        await run_batch(
            companies,
            item_key=lambda c: c.company_id,
            worker=_worker,
            results_path=run_store.results_path(run_id),
            errors_path=run_store.errors_path(run_id),
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
