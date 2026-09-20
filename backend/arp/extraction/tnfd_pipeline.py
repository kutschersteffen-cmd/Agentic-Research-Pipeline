from __future__ import annotations

import logging

from arp.config import Settings
from arp.extraction.tnfd_graph import extract_company_tnfd
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.batch_runner import run_batch
from arp.orchestration.cost_tracker import combine_usage, estimate_cost_usd
from arp.orchestration.job_manager import JobManager
from arp.orchestration.review_queue import queue_for_review
from arp.schemas.common import CompanyRef
from arp.schemas.tnfd import TNFDExtractionRecord
from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)


class TNFDExtractionResult:
    def __init__(self, record: TNFDExtractionRecord, usage: LLMUsage, cost_usd: float) -> None:
        self.record = record
        self.usage = usage
        self.cost_usd = cost_usd


async def _extract_company_tnfd(
    company: CompanyRef,
    *,
    run_id: str,
    as_of: str,
    registry: DocumentSourceRegistry,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    settings: Settings,
) -> TNFDExtractionResult:
    documents = await registry.fetch_all(company)
    record, usages = await extract_company_tnfd(
        company,
        documents=documents,
        run_id=run_id,
        as_of=as_of,
        llm=llm,
        verifier_llm=verifier_llm,
        settings=settings,
        fuzzy_threshold=settings.grounding_fuzzy_threshold,
        confidence_review_threshold=settings.confidence_review_threshold,
    )
    cost = sum(estimate_cost_usd(u.model or settings.llm_model, u) for u in usages)
    return TNFDExtractionResult(record, combine_usage(*usages) if usages else LLMUsage(), cost)


def create_tnfd_extraction_run(
    companies: list[CompanyRef], as_of: str, settings: Settings, run_store: RunStore
) -> str:
    job_manager = JobManager(run_store)
    manifest = job_manager.create_run(
        "tnfd", {"as_of": as_of}, len(companies), model=settings.llm_model, verifier_model=settings.llm_verifier_model
    )
    return manifest.run_id


async def execute_tnfd_extraction_run(
    run_id: str,
    companies: list[CompanyRef],
    as_of: str,
    *,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
) -> str:
    """Orchestrates the combined TNFD flow (one evidence gather + one
    extractor call + one independent verifier call per company ->
    programmatic grounding check -> aggregation) across the whole company
    universe, checkpointed and resumable, against an already-created run
    (see create_tnfd_extraction_run). `as_of` is the reporting period this
    run covers (e.g. "FY2025") -- applied to every company in the run, since
    a TNFD extraction run always targets one reporting period at a time."""
    job_manager = JobManager(run_store)

    def _on_success(company: CompanyRef, result: TNFDExtractionResult) -> None:
        if result.record.needs_review:
            queue_for_review(run_store, run_id, company.company_id, result.record.model_dump(mode="json"))
        job_manager.record_progress(
            run_id,
            completed_delta=1,
            review_delta=1 if result.record.needs_review else 0,
            input_tokens_delta=result.usage.input_tokens,
            output_tokens_delta=result.usage.output_tokens,
            cost_delta_usd=result.cost_usd,
        )

    def _on_error(company: CompanyRef, exc: Exception) -> None:
        job_manager.record_progress(run_id, failed_delta=1)

    def _cancel_check() -> bool:
        current = run_store.load_manifest(run_id)
        return current is not None and current.cancel_requested

    async def _worker(company: CompanyRef) -> TNFDExtractionResult:
        return await _extract_company_tnfd(
            company, run_id=run_id, as_of=as_of, registry=registry, llm=llm, verifier_llm=verifier_llm, settings=settings
        )

    await run_batch(
        companies,
        item_key=lambda c: c.company_id,
        worker=_worker,
        results_path=run_store.results_path(run_id),
        errors_path=run_store.errors_path(run_id),
        concurrency=settings.max_concurrent_llm_calls,
        result_to_json=lambda r: r.record.model_dump(mode="json"),
        on_success=_on_success,
        on_error=_on_error,
        cancel_check=_cancel_check,
    )

    job_manager.finish_run(run_id)
    return run_id


async def run_tnfd_extraction(
    companies: list[CompanyRef],
    as_of: str,
    *,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
) -> str:
    """Convenience wrapper (create + execute in one call) for synchronous
    callers such as the CLI, where blocking until completion is expected."""
    run_id = create_tnfd_extraction_run(companies, as_of, settings, run_store)
    return await execute_tnfd_extraction_run(
        run_id, companies, as_of, llm=llm, verifier_llm=verifier_llm, registry=registry, settings=settings, run_store=run_store
    )
