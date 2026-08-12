from __future__ import annotations

import logging

from arp.config import Settings
from arp.discovery.change_detector import ChangeDetector
from arp.discovery.crawler import CrawlConfig, crawl_for_documents
from arp.discovery.downloader import download_documents
from arp.discovery.site_finder import DuckDuckGoSearchClient, WebSearchClient, resolve_company_homepage
from arp.orchestration.batch_runner import run_batch
from arp.orchestration.job_manager import JobManager
from arp.schemas.common import CompanyRef, DocType
from arp.schemas.discovery import DiscoveryCompanyResult, DiscoveryRunParams
from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)


async def _discover_for_company(
    company: CompanyRef,
    *,
    settings: Settings,
    search_client: WebSearchClient,
    change_detector: ChangeDetector,
    doc_types: list[DocType] | None,
) -> DiscoveryCompanyResult:
    homepage = company.website
    if not homepage:
        homepage = await resolve_company_homepage(company.name, search_client)
    if not homepage:
        return DiscoveryCompanyResult(company_id=company.company_id, name=company.name, homepage_used=None)

    crawl_config = CrawlConfig(
        user_agent=settings.discovery_user_agent,
        max_depth=settings.discovery_max_crawl_depth,
        max_pages=settings.discovery_max_pages_per_company,
        request_delay_seconds=settings.discovery_request_delay_seconds,
    )
    candidates = await crawl_for_documents(homepage, crawl_config)
    if doc_types:
        candidates = [c for c in candidates if c.doc_type in doc_types]

    downloaded = await download_documents(company, candidates, settings.documents_dir, settings.discovery_user_agent)
    events = await change_detector.diff_and_record(company, downloaded)

    return DiscoveryCompanyResult(
        company_id=company.company_id,
        name=company.name,
        homepage_used=homepage,
        documents_found=downloaded,
        new_events=events,
    )


def create_discovery_run(
    companies: list[CompanyRef], doc_types: list[DocType] | None, triggered_by: str, run_store: RunStore
) -> str:
    job_manager = JobManager(run_store)
    params = DiscoveryRunParams(
        universe_source=f"{len(companies)} companies", doc_types=doc_types or [], triggered_by=triggered_by
    )
    manifest = job_manager.create_run("discovery", params.model_dump(mode="json"), len(companies))
    return manifest.run_id


async def execute_discovery_run(
    run_id: str,
    companies: list[CompanyRef],
    *,
    settings: Settings,
    run_store: RunStore,
    doc_types: list[DocType] | None = None,
    search_client: WebSearchClient | None = None,
) -> str:
    """Runs the document discovery pipeline over a company universe against
    an already-created run (see create_discovery_run).

    Shared by the manual API/CLI trigger and the periodic scheduler so both
    paths behave identically. Resumable and checkpointed via run_batch;
    every new/updated document raises a DocumentEvent through
    ChangeDetector (internal feed + optional webhook).
    """
    job_manager = JobManager(run_store)
    search_client = search_client or DuckDuckGoSearchClient(settings.discovery_user_agent)
    change_detector = ChangeDetector(
        state_dir=settings.discovery_state_dir,
        global_events_path=settings.documents_dir / "_events.jsonl",
        webhook_url=settings.discovery_webhook_url,
    )

    def _on_success(company: CompanyRef, result: DiscoveryCompanyResult) -> None:
        job_manager.record_progress(
            run_id,
            completed_delta=1,
            review_delta=1 if not result.homepage_used else 0,
        )

    def _on_error(company: CompanyRef, exc: Exception) -> None:
        job_manager.record_progress(run_id, failed_delta=1)

    await run_batch(
        companies,
        item_key=lambda c: c.company_id,
        worker=lambda c: _discover_for_company(
            c, settings=settings, search_client=search_client, change_detector=change_detector, doc_types=doc_types
        ),
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
