from __future__ import annotations

import logging

from arp.config import Settings
from arp.extraction.field_graph import extract_one_field
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.batch_runner import run_batch
from arp.orchestration.cost_tracker import combine_usage, estimate_cost_usd
from arp.orchestration.job_manager import JobManager
from arp.orchestration.review_queue import queue_for_review
from arp.schemas.common import CompanyRef, SourceDocument
from arp.schemas.datapoints import DataPointSchema, ExtractionRecord
from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)


class ExtractionRecordResult:
    def __init__(self, record: ExtractionRecord, usage: LLMUsage, cost_usd: float) -> None:
        self.record = record
        self.usage = usage
        self.cost_usd = cost_usd


async def _extract_company(
    company: CompanyRef,
    schema: DataPointSchema,
    *,
    registry: DocumentSourceRegistry,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    settings: Settings,
    documents: list[SourceDocument] | None = None,
) -> ExtractionRecordResult:
    """`documents`, when supplied, skips the registry fetch -- for callers
    (like the revenue-exposure resolver) that already fetched a company's
    documents once and are running several ad hoc single-field schemas
    against the same company, so a fresh fetch per field isn't repeated.

    `verifier_llm` defaults to `llm` only for callers that don't supply a
    separate model (see `extract_one_field`)."""
    if documents is None:
        documents = await registry.fetch_all(company)
    documents_by_id = {d.doc_id: d for d in documents}
    usages: list[LLMUsage] = []
    fields = []
    any_needs_review = False

    for field in schema.fields:
        extracted, needs_review, field_usages = await extract_one_field(
            company.name,
            field,
            documents=documents,
            documents_by_id=documents_by_id,
            llm=llm,
            verifier_llm=verifier_llm,
            settings=settings,
            fuzzy_threshold=settings.grounding_fuzzy_threshold,
            confidence_review_threshold=settings.confidence_review_threshold,
        )
        usages.extend(field_usages)

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
    # Cost is estimated per-call against the model that actually produced
    # each usage (extractor and verifier can now differ), then summed --
    # not against a single settings.llm_model, which would misprice every
    # verifier call once llm_verifier_model diverges from llm_model.
    cost = sum(estimate_cost_usd(u.model or settings.llm_model, u) for u in usages)
    return ExtractionRecordResult(record, combine_usage(*usages) if usages else LLMUsage(), cost)


def create_extraction_run(
    schema: DataPointSchema, companies: list[CompanyRef], settings: Settings, run_store: RunStore
) -> str:
    job_manager = JobManager(run_store)
    manifest = job_manager.create_run(
        "extraction",
        {"schema_id": schema.schema_id, "schema_name": schema.name},
        len(companies),
        model=settings.llm_model,
        verifier_model=settings.llm_verifier_model,
    )
    (run_store.run_dir(manifest.run_id) / "schema.json").write_text(schema.model_dump_json(indent=2))
    return manifest.run_id


async def execute_extraction_run(
    run_id: str,
    schema: DataPointSchema,
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
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

    async def _worker(company: CompanyRef) -> ExtractionRecordResult:
        result = await _extract_company(
            company, schema, registry=registry, llm=llm, verifier_llm=verifier_llm, settings=settings
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


async def run_extraction(
    schema: DataPointSchema,
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
) -> str:
    """Convenience wrapper (create + execute in one call) for synchronous
    callers such as the CLI, where blocking until completion is expected."""
    run_id = create_extraction_run(schema, companies, settings, run_store)
    return await execute_extraction_run(
        run_id, schema, companies, llm=llm, verifier_llm=verifier_llm, registry=registry, settings=settings, run_store=run_store
    )
