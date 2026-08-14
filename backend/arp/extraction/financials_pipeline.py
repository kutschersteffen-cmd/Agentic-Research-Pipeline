from __future__ import annotations

import logging

from arp.config import Settings
from arp.extraction.financials_graph import extract_company_financials
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.batch_runner import run_batch
from arp.orchestration.cost_tracker import combine_usage, estimate_cost_usd
from arp.orchestration.job_manager import JobManager
from arp.orchestration.review_queue import queue_for_review
from arp.schemas.common import CompanyRef
from arp.schemas.financials import CompanyFinancialsRecord
from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)


class FinancialsExtractionResult:
    def __init__(self, record: CompanyFinancialsRecord, usage: LLMUsage) -> None:
        self.record = record
        self.usage = usage


async def _extract_company_financials(
    company: CompanyRef,
    *,
    registry: DocumentSourceRegistry,
    llm: LLMClient,
    settings: Settings,
) -> FinancialsExtractionResult:
    documents = await registry.fetch_all(company)
    record, usages = await extract_company_financials(
        company,
        documents=documents,
        llm=llm,
        fuzzy_threshold=settings.grounding_fuzzy_threshold,
        confidence_review_threshold=settings.confidence_review_threshold,
    )
    return FinancialsExtractionResult(record, combine_usage(*usages) if usages else LLMUsage())


def create_financials_extraction_run(companies: list[CompanyRef], settings: Settings, run_store: RunStore) -> str:
    job_manager = JobManager(run_store)
    manifest = job_manager.create_run("financials", {}, len(companies), model=settings.llm_model)
    return manifest.run_id


async def execute_financials_extraction_run(
    run_id: str,
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
) -> str:
    """Orchestrates combined segments/CapEx/R&D extraction (one evidence
    gather + one extractor call + one independent verifier call per
    company -> programmatic grounding check -> aggregation) across the
    whole company universe, checkpointed and resumable, against an
    already-created run (see create_financials_extraction_run)."""
    job_manager = JobManager(run_store)

    def _on_success(company: CompanyRef, result: FinancialsExtractionResult) -> None:
        result.record.run_id = run_id
        if result.record.needs_review:
            queue_for_review(run_store, run_id, company.company_id, result.record.model_dump(mode="json"))
        cost = estimate_cost_usd(settings.llm_model, result.usage)
        job_manager.record_progress(
            run_id,
            completed_delta=1,
            review_delta=1 if result.record.needs_review else 0,
            input_tokens_delta=result.usage.input_tokens,
            output_tokens_delta=result.usage.output_tokens,
            cost_delta_usd=cost,
        )

    def _on_error(company: CompanyRef, exc: Exception) -> None:
        job_manager.record_progress(run_id, failed_delta=1)

    def _cancel_check() -> bool:
        current = run_store.load_manifest(run_id)
        return current is not None and current.cancel_requested

    async def _worker(company: CompanyRef) -> FinancialsExtractionResult:
        result = await _extract_company_financials(company, registry=registry, llm=llm, settings=settings)
        result.record.run_id = run_id
        return result

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


async def run_financials_extraction(
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
) -> str:
    """Convenience wrapper (create + execute in one call) for synchronous
    callers such as the CLI, where blocking until completion is expected."""
    run_id = create_financials_extraction_run(companies, settings, run_store)
    return await execute_financials_extraction_run(
        run_id, companies, llm=llm, registry=registry, settings=settings, run_store=run_store
    )
