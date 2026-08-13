from __future__ import annotations

import logging

from arp.config import Settings
from arp.extraction.financials_aggregator import build_financials_record
from arp.extraction.financials_extractor_agent import extract_financials
from arp.extraction.financials_verifier_agent import verify_financials
from arp.extraction.segment_extractor_agent import SEGMENT_DOC_TYPES, SEGMENT_KEYWORDS
from arp.extraction.spend_extractor_agent import SPEND_DOC_TYPES, SPEND_KEYWORDS
from arp.ingestion.parsing import chunk_document
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.batch_runner import run_batch
from arp.orchestration.cost_tracker import combine_usage, estimate_cost_usd
from arp.orchestration.job_manager import JobManager
from arp.orchestration.review_queue import queue_for_review
from arp.schemas.common import CompanyRef, DocumentChunk
from arp.schemas.financials import CompanyFinancialsRecord
from arp.schemas.spend import SpendTopic
from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)

# Union of every section's doc types/keywords -- fetched and chunked once
# per company rather than once per topic, since segments/capex/R&D are
# almost always wanted together.
FINANCIALS_DOC_TYPES = sorted(set(SEGMENT_DOC_TYPES) | set(SPEND_DOC_TYPES), key=lambda d: d.value)
_ALL_KEYWORDS = sorted(set(SEGMENT_KEYWORDS) | set(SPEND_KEYWORDS[SpendTopic.CAPEX]) | set(SPEND_KEYWORDS[SpendTopic.RND]))

_TOPIC_KEYWORD_SETS: dict[str, set[str]] = {
    "segments": {k.lower() for k in SEGMENT_KEYWORDS},
    "capex": {k.lower() for k in SPEND_KEYWORDS[SpendTopic.CAPEX]},
    "rnd": {k.lower() for k in SPEND_KEYWORDS[SpendTopic.RND]},
}
_MAX_CHUNKS_PER_TOPIC = 10


def _select_evidence(chunks: list[DocumentChunk]) -> list[DocumentChunk]:
    """Per-topic keyword-in-context prefilter, ranked by hit count and
    capped per topic, then unioned/deduped -- so a topic with sparser
    evidence (e.g. a single CapEx sentence in a filing dominated by segment
    discussion) still gets its own guaranteed slice of the evidence sent to
    the single combined extractor call, instead of being crowded out by a
    single global ranking.
    """
    selected: dict[str, DocumentChunk] = {}
    for keyword_set in _TOPIC_KEYWORD_SETS.values():
        scored = [(len([h for h in c.keyword_hits if h.lower() in keyword_set]), c) for c in chunks]
        scored = [(score, c) for score, c in scored if score > 0]
        scored.sort(key=lambda sc: sc[0], reverse=True)
        for _, c in scored[:_MAX_CHUNKS_PER_TOPIC]:
            selected[c.chunk_id] = c
    return list(selected.values())


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
    documents_by_id = {d.doc_id: d for d in documents}

    all_chunks: list[DocumentChunk] = []
    for doc in documents:
        if doc.doc_type not in FINANCIALS_DOC_TYPES:
            continue
        all_chunks.extend(chunk_document(doc, keywords=_ALL_KEYWORDS))
    evidence = _select_evidence(all_chunks)

    if not evidence:
        # No matching evidence at all is the common case at scale (docs not
        # fetched, or the company simply doesn't discuss any of this) --
        # report plainly rather than flooding the review queue.
        record = CompanyFinancialsRecord(company_id=company.company_id, ticker=company.ticker, name=company.name, run_id="")
        return FinancialsExtractionResult(record, LLMUsage())

    draft, u1 = await extract_financials(company.name, evidence, llm)
    verifier, u2 = await verify_financials(company.name, evidence, draft, llm)
    record, _needs_review = build_financials_record(
        company.company_id,
        company.ticker,
        company.name,
        draft,
        verifier,
        documents_by_id,
        settings.grounding_fuzzy_threshold,
        settings.confidence_review_threshold,
    )
    return FinancialsExtractionResult(record, combine_usage(u1, u2))


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
