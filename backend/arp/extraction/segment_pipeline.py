from __future__ import annotations

import logging

from arp.config import Settings
from arp.extraction.segment_aggregator import build_segments
from arp.extraction.segment_extractor_agent import extract_segments
from arp.extraction.segment_verifier_agent import verify_segments
from arp.ingestion.parsing import chunk_document
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.batch_runner import run_batch
from arp.orchestration.cost_tracker import combine_usage, estimate_cost_usd
from arp.orchestration.job_manager import JobManager
from arp.orchestration.review_queue import queue_for_review
from arp.schemas.common import CompanyRef, DocType
from arp.schemas.segments import SegmentExtractionRecord
from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)

# Segment reporting figures live almost exclusively in the annual filing's
# "Segment Information" note, occasionally restated in an investor deck.
SEGMENT_DOC_TYPES = [DocType.ANNUAL_REPORT_10K, DocType.PROXY_DEF14A, DocType.INVESTOR_PRESENTATION]

SEGMENT_KEYWORDS = [
    "segment",
    "segments",
    "reportable segment",
    "reportable segments",
    "operating segment",
    "operating segments",
    "business segment",
    "segment revenue",
    "segment income",
    "segment profit",
    "segment assets",
    "revenue by segment",
    "segment reporting",
    "reconciliation of segment",
]

_MAX_EVIDENCE_CHUNKS = 20


def _select_evidence(chunks: list, max_chunks: int = _MAX_EVIDENCE_CHUNKS) -> list:
    """Keyword-in-context prefilter, ranked by hit count -- the same
    precision-at-cost tradeoff as the scalar extraction engine's chunk
    selector, sized larger here since segment reporting tables/notes tend
    to span more of the filing than a single data point.
    """
    candidates = [c for c in chunks if c.keyword_hits]
    candidates.sort(key=lambda c: len(c.keyword_hits), reverse=True)
    return candidates[:max_chunks]


class SegmentExtractionResult:
    def __init__(self, record: SegmentExtractionRecord, usage: LLMUsage) -> None:
        self.record = record
        self.usage = usage


async def _extract_company_segments(
    company: CompanyRef,
    *,
    registry: DocumentSourceRegistry,
    llm: LLMClient,
    settings: Settings,
) -> SegmentExtractionResult:
    documents = await registry.fetch_all(company)
    documents_by_id = {d.doc_id: d for d in documents}

    all_chunks = []
    for doc in documents:
        if doc.doc_type not in SEGMENT_DOC_TYPES:
            continue
        all_chunks.extend(chunk_document(doc, keywords=SEGMENT_KEYWORDS))
    evidence = _select_evidence(all_chunks)

    if not evidence:
        # No segment-reporting evidence at all is the common case at scale
        # (single-segment companies, or docs simply not fetched) -- report
        # plainly rather than flooding the review queue, mirroring the
        # scalar extraction engine's no-evidence handling.
        record = SegmentExtractionRecord(
            company_id=company.company_id,
            ticker=company.ticker,
            name=company.name,
            run_id="",
            segments=[],
            overall_confidence=0.0,
            needs_review=False,
        )
        return SegmentExtractionResult(record, LLMUsage())

    draft, u1 = await extract_segments(company.name, evidence, llm)
    verifier, u2 = await verify_segments(company.name, evidence, draft, llm)
    segments, needs_review = build_segments(
        draft, verifier, documents_by_id, settings.grounding_fuzzy_threshold, settings.confidence_review_threshold
    )

    confidences = [s.confidence for s in segments]
    overall_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    record = SegmentExtractionRecord(
        company_id=company.company_id,
        ticker=company.ticker,
        name=company.name,
        run_id="",
        segments=segments,
        overall_confidence=overall_confidence,
        needs_review=needs_review,
    )
    return SegmentExtractionResult(record, combine_usage(u1, u2))


def create_segment_extraction_run(companies: list[CompanyRef], settings: Settings, run_store: RunStore) -> str:
    job_manager = JobManager(run_store)
    manifest = job_manager.create_run("segments", {}, len(companies), model=settings.llm_model)
    return manifest.run_id


async def execute_segment_extraction_run(
    run_id: str,
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
) -> str:
    """Orchestrates business-segment extraction (extractor -> independent
    verifier -> programmatic grounding check -> aggregation) across the
    whole company universe, checkpointed and resumable, against an
    already-created run (see create_segment_extraction_run)."""
    job_manager = JobManager(run_store)

    def _on_success(company: CompanyRef, result: SegmentExtractionResult) -> None:
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

    async def _worker(company: CompanyRef) -> SegmentExtractionResult:
        result = await _extract_company_segments(company, registry=registry, llm=llm, settings=settings)
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


async def run_segment_extraction(
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
) -> str:
    """Convenience wrapper (create + execute in one call) for synchronous
    callers such as the CLI, where blocking until completion is expected."""
    run_id = create_segment_extraction_run(companies, settings, run_store)
    return await execute_segment_extraction_run(
        run_id, companies, llm=llm, registry=registry, settings=settings, run_store=run_store
    )
