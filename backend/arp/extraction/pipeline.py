from __future__ import annotations

import logging

from arp.config import Settings
from arp.extraction.aggregator import build_extracted_field, no_evidence_field
from arp.extraction.extractor_agent import extract_field
from arp.extraction.verifier_agent import verify_extraction
from arp.ingestion.parsing import chunk_document
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.batch_runner import run_batch
from arp.orchestration.cost_tracker import combine_usage, estimate_cost_usd
from arp.orchestration.job_manager import JobManager
from arp.orchestration.review_queue import queue_for_review
from arp.retrieval.select_evidence import select_relevant_chunks
from arp.schemas.common import CompanyRef, SourceDocument
from arp.schemas.datapoints import DataPointSchema, ExtractionRecord
from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)


class ExtractionRecordResult:
    def __init__(self, record: ExtractionRecord, usage: LLMUsage) -> None:
        self.record = record
        self.usage = usage


async def _extract_company(
    company: CompanyRef,
    schema: DataPointSchema,
    *,
    registry: DocumentSourceRegistry,
    llm: LLMClient,
    settings: Settings,
    documents: list[SourceDocument] | None = None,
) -> ExtractionRecordResult:
    """`documents`, when supplied, skips the registry fetch -- for callers
    (like the revenue-exposure resolver) that already fetched a company's
    documents once and are running several ad hoc single-field schemas
    against the same company, so a fresh fetch per field isn't repeated."""
    if documents is None:
        documents = await registry.fetch_all(company)
    documents_by_id = {d.doc_id: d for d in documents}
    usages: list[LLMUsage] = []
    fields = []
    any_needs_review = False

    for field in schema.fields:
        all_chunks = []
        for doc in documents:
            if field.source_doc_types and doc.doc_type not in field.source_doc_types:
                continue
            all_chunks.extend(chunk_document(doc, keywords=field.seed_keywords))
        evidence = select_relevant_chunks(all_chunks, field.seed_keywords, doc_type_filter=field.source_doc_types or None)

        if not evidence:
            extracted, needs_review = no_evidence_field(field)
        else:
            draft, u1 = await extract_field(company.name, field, evidence, llm)
            verifier, u2 = await verify_extraction(company.name, field, evidence, draft, llm)
            usages.extend([u1, u2])
            extracted, needs_review = build_extracted_field(
                field,
                draft,
                verifier,
                documents_by_id,
                settings.grounding_fuzzy_threshold,
                settings.confidence_review_threshold,
            )

        any_needs_review = any_needs_review or needs_review
        fields.append((extracted, needs_review))

    confidences = [f.confidence for f, _ in fields if f.value is not None]
    overall_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    record = ExtractionRecord(
        company_id=company.company_id,
        ticker=company.ticker,
        name=company.name,
        schema_id=schema.schema_id,
        run_id="",  # filled in by caller once run_id is known
        fields=[f for f, _ in fields],
        overall_confidence=overall_confidence,
        needs_review=any_needs_review,
    )
    return ExtractionRecordResult(record, combine_usage(*usages) if usages else LLMUsage())


def create_extraction_run(
    schema: DataPointSchema, companies: list[CompanyRef], settings: Settings, run_store: RunStore
) -> str:
    job_manager = JobManager(run_store)
    manifest = job_manager.create_run(
        "extraction",
        {"schema_id": schema.schema_id, "schema_name": schema.name},
        len(companies),
        model=settings.llm_model,
    )
    (run_store.run_dir(manifest.run_id) / "schema.json").write_text(schema.model_dump_json(indent=2))
    return manifest.run_id


async def execute_extraction_run(
    run_id: str,
    schema: DataPointSchema,
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
) -> str:
    """Orchestrates schema-driven extraction (extractor -> independent
    verifier -> programmatic grounding check -> aggregation) across the
    whole company universe, checkpointed and resumable for 4000+ company
    batches, against an already-created run (see create_extraction_run).
    """
    job_manager = JobManager(run_store)

    def _on_success(company: CompanyRef, result: ExtractionRecordResult) -> None:
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

    async def _worker(company: CompanyRef) -> ExtractionRecordResult:
        result = await _extract_company(company, schema, registry=registry, llm=llm, settings=settings)
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


async def run_extraction(
    schema: DataPointSchema,
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
) -> str:
    """Convenience wrapper (create + execute in one call) for synchronous
    callers such as the CLI, where blocking until completion is expected."""
    run_id = create_extraction_run(schema, companies, settings, run_store)
    return await execute_extraction_run(
        run_id, schema, companies, llm=llm, registry=registry, settings=settings, run_store=run_store
    )
