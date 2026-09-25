from __future__ import annotations

import logging

from arp.config import Settings
from arp.extraction.tnfd_graph import extract_company_tnfd
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.batch_runner import run_company_batch
from arp.orchestration.cost_tracker import combine_usage, estimate_cost_usd
from arp.orchestration.job_manager import JobManager
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

    async def _worker(company: CompanyRef) -> TNFDExtractionResult:
        return await _extract_company_tnfd(
            company, run_id=run_id, as_of=as_of, registry=registry, llm=llm, verifier_llm=verifier_llm, settings=settings
        )

    await run_company_batch(
        run_id,
        companies,
        run_store=run_store,
        worker=_worker,
        result_to_json=lambda r: r.record.model_dump(mode="json"),
        review_items=lambda c, r: [(c.company_id, r.record.model_dump(mode="json"))] if r.record.needs_review else [],
        cost_usd=lambda r: r.cost_usd,
        concurrency=settings.max_concurrent_llm_calls,
    )
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
