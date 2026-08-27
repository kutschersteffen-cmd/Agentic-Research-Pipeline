from __future__ import annotations

import logging

from arp.config import Settings
from arp.extraction.financials_graph import extract_company_financials
from arp.ingestion.registry import DocumentSourceRegistry
from arp.ingestion.xbrl import XbrlFactSource
from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.batch_runner import run_batch
from arp.orchestration.cost_tracker import combine_usage, estimate_cost_usd
from arp.orchestration.job_manager import JobManager
from arp.orchestration.review_queue import queue_for_review
from arp.schemas.common import CompanyRef
from arp.schemas.financials import CompanyFinancialsRecord
from arp.schemas.spend import AmountMetric
from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)


class FinancialsExtractionResult:
    def __init__(self, record: CompanyFinancialsRecord, usage: LLMUsage, cost_usd: float) -> None:
        self.record = record
        self.usage = usage
        self.cost_usd = cost_usd


async def _overlay_xbrl_facts(
    record: CompanyFinancialsRecord, company: CompanyRef, xbrl_source: XbrlFactSource
) -> CompanyFinancialsRecord:
    """Path 0 ahead of the LLM pipeline's own capex/rnd totals: if SEC's
    structured XBRL data has a figure for this EDGAR filer, it replaces
    the LLM-extracted total outright -- a hard, machine-tagged fact from
    the company's own filing is strictly more trustworthy than an LLM's
    read of prose, the same precedence the revenue/CapEx catalogue cascade
    (arp/research/revenue_exposure/resolver.py) already applies. Only the
    scalar `total` is replaced; `description`/`categories` (XBRL has no
    plain-language breakdown) and everything else the LLM pass produced
    (segments, needs_review from other reasons) are left untouched.
    """
    cik = await xbrl_source.resolve_cik(company.cik, company.ticker)
    if not cik:
        return record
    facts = await xbrl_source.fetch_capex_rnd_revenue(company.company_id, cik)
    if facts is None:
        return record

    updates: dict = {}
    if facts.capex is not None:
        updates["capex"] = record.capex.model_copy(
            update={
                "total": AmountMetric(
                    value=facts.capex.value,
                    raw_value_text=f"{facts.capex.value:,.0f} {facts.capex.unit} (SEC XBRL, us-gaap:{facts.capex.tag})",
                    citations=[facts.capex.as_citation(cik)],
                    grounded=True,
                ),
                "confidence": 1.0,
                "grounded": True,
            }
        )
    if facts.rnd is not None:
        updates["rnd"] = record.rnd.model_copy(
            update={
                "total": AmountMetric(
                    value=facts.rnd.value,
                    raw_value_text=f"{facts.rnd.value:,.0f} {facts.rnd.unit} (SEC XBRL, us-gaap:{facts.rnd.tag})",
                    citations=[facts.rnd.as_citation(cik)],
                    grounded=True,
                ),
                "confidence": 1.0,
                "grounded": True,
            }
        )
    if not updates:
        return record
    return record.model_copy(update=updates)


async def _extract_company_financials(
    company: CompanyRef,
    *,
    registry: DocumentSourceRegistry,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    settings: Settings,
    xbrl_source: XbrlFactSource | None = None,
) -> FinancialsExtractionResult:
    documents = await registry.fetch_all(company)
    record, usages = await extract_company_financials(
        company,
        documents=documents,
        llm=llm,
        verifier_llm=verifier_llm,
        settings=settings,
        fuzzy_threshold=settings.grounding_fuzzy_threshold,
        confidence_review_threshold=settings.confidence_review_threshold,
    )
    if xbrl_source is not None and settings.xbrl_facts_enabled:
        record = await _overlay_xbrl_facts(record, company, xbrl_source)
    cost = sum(estimate_cost_usd(u.model or settings.llm_model, u) for u in usages)
    return FinancialsExtractionResult(record, combine_usage(*usages) if usages else LLMUsage(), cost)


def create_financials_extraction_run(companies: list[CompanyRef], settings: Settings, run_store: RunStore) -> str:
    job_manager = JobManager(run_store)
    manifest = job_manager.create_run(
        "financials", {}, len(companies), model=settings.llm_model, verifier_model=settings.llm_verifier_model
    )
    return manifest.run_id


async def execute_financials_extraction_run(
    run_id: str,
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
    xbrl_source: XbrlFactSource | None = None,
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

    async def _worker(company: CompanyRef) -> FinancialsExtractionResult:
        result = await _extract_company_financials(
            company, registry=registry, llm=llm, verifier_llm=verifier_llm, settings=settings, xbrl_source=xbrl_source
        )
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
    verifier_llm: LLMClient | None = None,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
    xbrl_source: XbrlFactSource | None = None,
) -> str:
    """Convenience wrapper (create + execute in one call) for synchronous
    callers such as the CLI, where blocking until completion is expected."""
    run_id = create_financials_extraction_run(companies, settings, run_store)
    return await execute_financials_extraction_run(
        run_id,
        companies,
        llm=llm,
        verifier_llm=verifier_llm,
        registry=registry,
        settings=settings,
        run_store=run_store,
        xbrl_source=xbrl_source,
    )
