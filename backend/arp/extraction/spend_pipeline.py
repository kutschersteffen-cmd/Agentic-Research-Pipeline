from __future__ import annotations

import logging

from arp.config import Settings
from arp.extraction.spend_aggregator import build_spend_record
from arp.extraction.spend_extractor_agent import extract_spend
from arp.extraction.spend_verifier_agent import verify_spend
from arp.ingestion.parsing import chunk_document
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.batch_runner import run_batch
from arp.orchestration.cost_tracker import combine_usage, estimate_cost_usd
from arp.orchestration.job_manager import JobManager
from arp.orchestration.review_queue import queue_for_review
from arp.schemas.common import CompanyRef, DocType
from arp.schemas.spend import SpendExtractionRecord, SpendTopic
from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)

# CapEx/R&D figures and their qualitative discussion show up more broadly
# than segment reporting notes: 10-Ks, sustainability reports (green capex),
# investor decks, and earnings call commentary.
SPEND_DOC_TYPES = [
    DocType.ANNUAL_REPORT_10K,
    DocType.SUSTAINABILITY_REPORT,
    DocType.INVESTOR_PRESENTATION,
    DocType.EARNINGS_TRANSCRIPT,
]

SPEND_KEYWORDS: dict[SpendTopic, list[str]] = {
    SpendTopic.CAPEX: [
        "capital expenditure",
        "capital expenditures",
        "capex",
        "capital investment",
        "purchases of property and equipment",
        "property, plant and equipment",
        "capitalized software",
        "additions to property, plant and equipment",
        "investing activities",
    ],
    SpendTopic.RND: [
        "research and development",
        "r&d expense",
        "r&d expenditure",
        "research and development costs",
        "product development",
        "engineering and development",
    ],
}

_MAX_EVIDENCE_CHUNKS = 20


def _select_evidence(chunks: list, max_chunks: int = _MAX_EVIDENCE_CHUNKS) -> list:
    """Keyword-in-context prefilter, ranked by hit count -- same
    precision-at-cost tradeoff as the other extraction pipelines."""
    candidates = [c for c in chunks if c.keyword_hits]
    candidates.sort(key=lambda c: len(c.keyword_hits), reverse=True)
    return candidates[:max_chunks]


class SpendExtractionResult:
    def __init__(self, record: SpendExtractionRecord, usage: LLMUsage) -> None:
        self.record = record
        self.usage = usage


async def _extract_company_spend(
    topic: SpendTopic,
    company: CompanyRef,
    *,
    registry: DocumentSourceRegistry,
    llm: LLMClient,
    settings: Settings,
) -> SpendExtractionResult:
    documents = await registry.fetch_all(company)
    documents_by_id = {d.doc_id: d for d in documents}

    all_chunks = []
    for doc in documents:
        if doc.doc_type not in SPEND_DOC_TYPES:
            continue
        all_chunks.extend(chunk_document(doc, keywords=SPEND_KEYWORDS[topic]))
    evidence = _select_evidence(all_chunks)

    if not evidence:
        # No matching evidence at all is the common case at scale (doc not
        # fetched, or the company simply doesn't discuss this) -- report
        # plainly rather than flooding the review queue.
        record = SpendExtractionRecord(
            company_id=company.company_id, ticker=company.ticker, name=company.name, topic=topic, run_id=""
        )
        return SpendExtractionResult(record, LLMUsage())

    draft, u1 = await extract_spend(topic, company.name, evidence, llm)
    verifier, u2 = await verify_spend(topic, company.name, evidence, draft, llm)
    record, needs_review = build_spend_record(
        topic,
        company.company_id,
        company.ticker,
        company.name,
        draft,
        verifier,
        documents_by_id,
        settings.grounding_fuzzy_threshold,
        settings.confidence_review_threshold,
    )
    return SpendExtractionResult(record, combine_usage(u1, u2))


def create_spend_extraction_run(
    topic: SpendTopic, companies: list[CompanyRef], settings: Settings, run_store: RunStore
) -> str:
    job_manager = JobManager(run_store)
    manifest = job_manager.create_run("spend", {"topic": topic.value}, len(companies), model=settings.llm_model)
    return manifest.run_id


async def execute_spend_extraction_run(
    run_id: str,
    topic: SpendTopic,
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
) -> str:
    """Orchestrates CapEx/R&D extraction (extractor -> independent verifier
    -> programmatic grounding check -> aggregation) across the whole company
    universe, checkpointed and resumable, against an already-created run
    (see create_spend_extraction_run)."""
    job_manager = JobManager(run_store)

    def _on_success(company: CompanyRef, result: SpendExtractionResult) -> None:
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

    async def _worker(company: CompanyRef) -> SpendExtractionResult:
        result = await _extract_company_spend(topic, company, registry=registry, llm=llm, settings=settings)
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


async def run_spend_extraction(
    topic: SpendTopic,
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
) -> str:
    """Convenience wrapper (create + execute in one call) for synchronous
    callers such as the CLI, where blocking until completion is expected."""
    run_id = create_spend_extraction_run(topic, companies, settings, run_store)
    return await execute_spend_extraction_run(
        run_id, topic, companies, llm=llm, registry=registry, settings=settings, run_store=run_store
    )
