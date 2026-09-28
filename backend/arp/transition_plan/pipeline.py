from __future__ import annotations

import logging

from arp.config import Settings
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.batch_runner import run_company_batch
from arp.orchestration.cost_tracker import combine_usage, estimate_cost_usd
from arp.orchestration.job_manager import JobManager
from arp.schemas.common import CompanyRef
from arp.schemas.transition_plan import TransitionPlanAssessmentRecord
from arp.storage.run_store import RunStore
from arp.transition_plan.company_assessment import assess_company_transition_plan

logger = logging.getLogger(__name__)


class TransitionPlanAssessmentResult:
    def __init__(self, record: TransitionPlanAssessmentRecord, usage: LLMUsage, cost_usd: float) -> None:
        self.record = record
        self.usage = usage
        self.cost_usd = cost_usd


async def _assess_company(
    company: CompanyRef,
    *,
    registry: DocumentSourceRegistry,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    settings: Settings,
) -> TransitionPlanAssessmentResult:
    documents = await registry.fetch_all(company)
    record, usages = await assess_company_transition_plan(
        company,
        documents=documents,
        llm=llm,
        verifier_llm=verifier_llm,
        settings=settings,
        fuzzy_threshold=settings.grounding_fuzzy_threshold,
    )
    # Priced per call against the model that made it -- the verify step runs
    # on a different model, as in arp/extraction/pipeline.py.
    cost = sum(estimate_cost_usd(u.model or settings.llm_model, u) for u in usages)
    return TransitionPlanAssessmentResult(record, combine_usage(*usages) if usages else LLMUsage(), cost)


def create_transition_plan_run(companies: list[CompanyRef], settings: Settings, run_store: RunStore) -> str:
    job_manager = JobManager(run_store)
    manifest = job_manager.create_run(
        "transition_plan", {}, len(companies), model=settings.llm_model, verifier_model=settings.llm_verifier_model
    )
    return manifest.run_id


async def execute_transition_plan_run(
    run_id: str,
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
) -> str:
    """Orchestrates the 64-indicator transition plan assessment (evidence
    select -> RAG verdict -> programmatic grounding check -> aggregation,
    per indicator) across the whole company universe, checkpointed and
    resumable for large batches, against an already-created run (see
    create_transition_plan_run).
    """

    async def _worker(company: CompanyRef) -> TransitionPlanAssessmentResult:
        result = await _assess_company(company, registry=registry, llm=llm, verifier_llm=verifier_llm, settings=settings)
        result.record.run_id = run_id
        return result

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


async def run_transition_plan_assessment(
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
    run_id = create_transition_plan_run(companies, settings, run_store)
    return await execute_transition_plan_run(
        run_id, companies, llm=llm, verifier_llm=verifier_llm, registry=registry, settings=settings, run_store=run_store
    )
