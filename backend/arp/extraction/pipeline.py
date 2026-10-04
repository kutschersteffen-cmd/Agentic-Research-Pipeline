from __future__ import annotations

import logging

from arp.checks.runner import CheckContext, check_record  # isort: skip -- loads before prior_period (import cycle)
from arp.checks.prior_period import open_restatement_candidates
from arp.config import Settings
from arp.extraction.field_graph import extract_one_field
from arp.extraction.history import RunHistory
from arp.extraction.pre_steps import prepare_company
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.batch_runner import run_company_batch
from arp.orchestration.cost_tracker import combine_usage, estimate_cost_usd
from arp.orchestration.job_manager import JobManager
from arp.schemas.common import CompanyRef, SourceDocument
from arp.schemas.datapoints import DataPointSchema, ExtractionRecord, FieldStatus
from arp.schemas.issuer import issuer_key
from arp.schemas.review import field_item_key, period_key
from arp.storage.run_store import RunStore
from arp.storage.schema_registry import SchemaRegistry, UnreleasedFieldError

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
    history: RunHistory | None = None,
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
            schema_version=f"{schema.schema_id}:v{schema.version}",
            fiscal_year_end=company.fiscal_year_end,
        )
        usages.extend(field_usages)

        fields.extend(extracted)

    key, scheme = issuer_key(company)
    fields = await check_record(
        schema,
        fields,
        CheckContext(
            company=company,
            issuer_key=key,
            schema=schema,
            documents_by_id=documents_by_id,
            record_fields=fields,
            history=history,
        ),
    )

    confidences = [f.confidence for f in fields if f.value is not None]
    overall_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    record = ExtractionRecord(
        company_id=company.company_id,
        ticker=company.ticker,
        name=company.name,
        schema_id=schema.schema_id,
        run_id="",  # filled in by caller once run_id is known
        issuer_key=key,
        issuer_scheme=scheme,
        fields=fields,
        overall_confidence=overall_confidence,
        needs_review=any(f.review_reasons for f in fields),
    )
    # Cost is estimated per-call against the model that actually produced
    # each usage (extractor and verifier can now differ), then summed --
    # not against a single settings.llm_model, which would misprice every
    # verifier call once llm_verifier_model diverges from llm_model.
    cost = sum(estimate_cost_usd(u.model or settings.llm_model, u) for u in usages)
    return ExtractionRecordResult(record, combine_usage(*usages) if usages else LLMUsage(), cost)


def create_extraction_run(
    schema: DataPointSchema, companies: list[CompanyRef], settings: Settings, run_store: RunStore, *, trial: bool = False
) -> str:
    """Registers the schema, then refuses to start unless it is released
    (every field `released`) or the run is a `trial`. The registered copy
    is the run's `schema.json` snapshot."""
    registered = SchemaRegistry(settings.schema_registry_dir).save(schema)
    if not trial:
        bad = [f.field_id for f in registered.fields if f.status != FieldStatus.RELEASED]
        if not registered.release_flag or bad:
            raise UnreleasedFieldError(
                f"Schema {registered.schema_id} v{registered.version} is not released"
                + (f"; fields not released: {', '.join(bad)}" if bad else "")
                + ". Release it, or start a trial run."
            )
    job_manager = JobManager(run_store)
    manifest = job_manager.create_run(
        "extraction",
        {
            "schema_id": registered.schema_id,
            "schema_name": registered.name,
            "schema_version": f"{registered.schema_id}:v{registered.version}",
            "trial": trial,
        },
        len(companies),
        model=settings.llm_model,
        verifier_model=settings.llm_verifier_model,
    )
    (run_store.run_dir(manifest.run_id) / "schema.json").write_text(registered.model_dump_json(indent=2))
    return manifest.run_id


def load_run_schema(run_store: RunStore, run_id: str) -> DataPointSchema | None:
    path = run_store.run_dir(run_id) / "schema.json"
    return DataPointSchema.model_validate_json(path.read_text()) if path.exists() else None


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
    schema = load_run_schema(run_store, run_id) or schema  # the registered snapshot

    def _review_items(company: CompanyRef, result: ExtractionRecordResult) -> list[tuple[str, dict]]:
        rec = result.record
        return [
            (
                field_item_key(rec.issuer_key, f.field_id, period_key(f)),
                {
                    "item_key": field_item_key(rec.issuer_key, f.field_id, period_key(f)),
                    "issuer_key": rec.issuer_key,
                    "issuer_scheme": rec.issuer_scheme,
                    "company_id": rec.company_id,
                    "name": rec.name,
                    "schema_id": rec.schema_id,
                    "run_id": rec.run_id,
                    "field_id": f.field_id,
                    "period_end": f.period_end,
                    "field": f.model_dump(mode="json"),
                    "reason_codes": [str(r) for r in f.review_reasons],
                },
            )
            for f in rec.fields
            if f.review_reasons
        ]

    history = RunHistory.load(run_store, exclude_run_id=run_id)

    async def _worker(company: CompanyRef) -> ExtractionRecordResult:
        company = await prepare_company(company, settings=settings, llm=llm, registry=registry)
        result = await _extract_company(
            company, schema, registry=registry, llm=llm, verifier_llm=verifier_llm, settings=settings,
            history=history,
        )
        result.record.run_id = run_id
        open_restatement_candidates(run_store, run_id, result.record, history)
        return result

    await run_company_batch(
        run_id,
        companies,
        run_store=run_store,
        worker=_worker,
        result_to_json=lambda r: r.record.model_dump(mode="json"),
        review_items=_review_items,
        cost_usd=lambda r: r.cost_usd,
        concurrency=settings.max_concurrent_llm_calls,
    )
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
    trial: bool = False,
) -> str:
    """Convenience wrapper (create + execute in one call) for synchronous
    callers such as the CLI, where blocking until completion is expected."""
    run_id = create_extraction_run(schema, companies, settings, run_store, trial=trial)
    return await execute_extraction_run(
        run_id, schema, companies, llm=llm, verifier_llm=verifier_llm, registry=registry, settings=settings, run_store=run_store
    )
