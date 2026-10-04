from __future__ import annotations

import logging

from arp.checks.prior_period import open_restatement_candidates
from arp.checks.runner import CheckContext, check_record
from arp.config import Settings
from arp.extraction.field_graph import extract_one_field
from arp.extraction.history import RunHistory
from arp.extraction.pre_steps import prepare_company
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.batch_runner import run_company_batch
from arp.orchestration.cost_tracker import combine_usage, estimate_cost_usd
from arp.orchestration.job_manager import JobManager
from arp.planning.applicability import plan_fields
from arp.planning.doc_routing import input_hash, route_documents
from arp.planning.entity_check import confirm_entity
from arp.planning.periods import plan_periods, union_planned
from arp.schemas.common import CompanyRef, MatchStatus, SourceDocument
from arp.schemas.datapoints import DataPointSchema, ExtractedField, ExtractionRecord, FieldStatus
from arp.schemas.issuer import issuer_key
from arp.schemas.review import field_item_key, period_key
from arp.storage.identifier_map import IdentifierMapStore
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
    identifier_map: IdentifierMapStore | None = None,
) -> ExtractionRecordResult:
    """`documents`, when supplied, skips the registry fetch -- for callers
    (like the revenue-exposure resolver) that already fetched a company's
    documents once and are running several ad hoc single-field schemas
    against the same company, so a fresh fetch per field isn't repeated.

    `verifier_llm` defaults to `llm` only for callers that don't supply a
    separate model (see `extract_one_field`)."""
    if documents is None:
        documents = await registry.fetch_all(company)
    documents = [confirm_entity(d, company, identifier_map) for d in documents]
    documents_by_id = {d.doc_id: d for d in documents}  # all docs, held ones included
    kept = [d for d in documents if d.match_status != MatchStatus.MISMATCH]
    held = [
        {"doc_id": d.doc_id, "title": d.title, "covered_entity": d.covered_entity, "match_status": d.match_status.value}
        for d in documents
        if d.match_status == MatchStatus.MISMATCH
    ]
    usages: list[LLMUsage] = []
    to_extract, fields = plan_fields(schema, company)
    key, scheme = issuer_key(company)
    recorded = history.recorded_periods(key) if history else set()
    for d in kept:
        d.period_plan = plan_periods(d, fiscal_year_end=company.fiscal_year_end, recorded=recorded)
    planned_periods = union_planned(kept)

    for field in to_extract:
        h = input_hash(field, route_documents(field, kept), planned_periods)
        prior = history.last_rows(company.company_id, field.field_id) if history and h else []
        if prior and all(r.get("input_hash") == h and (r.get("provenance") or {}).get("field_version") == field.version for r in prior):
            run = history.last_run_id(company.company_id)
            fields.extend(
                ExtractedField.model_validate(r).model_copy(
                    update={"reused_from_run": run, "checks": [], "route_reasons": []}
                )
                for r in prior
            )
            continue
        extracted, needs_review, field_usages = await extract_one_field(
            company.name,
            field,
            documents=kept,
            documents_by_id=documents_by_id,
            llm=llm,
            verifier_llm=verifier_llm,
            settings=settings,
            fuzzy_threshold=settings.grounding_fuzzy_threshold,
            confidence_review_threshold=settings.confidence_review_threshold,
            schema_version=f"{schema.schema_id}:v{schema.version}",
            fiscal_year_end=company.fiscal_year_end,
            planned_periods=planned_periods,
        )
        usages.extend(field_usages)

        fields.extend(f.model_copy(update={"input_hash": h}) for f in extracted)

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
        held_documents=held,
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
    identifier_map = IdentifierMapStore(settings.identifier_map_path)

    async def _worker(company: CompanyRef) -> ExtractionRecordResult:
        company = await prepare_company(company, settings=settings, llm=llm, registry=registry)
        result = await _extract_company(
            company, schema, registry=registry, llm=llm, verifier_llm=verifier_llm, settings=settings,
            history=history, identifier_map=identifier_map,
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
