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
    def __init__(self, record: TransitionPlanAssessmentRecord, usage: LLMUsage) -> None:
        self.record = record
        self.usage = usage


async def _assess_company(
    company: CompanyRef,
    *,
    registry: DocumentSourceRegistry,
    llm: LLMClient,
    settings: Settings,
) -> TransitionPlanAssessmentResult:
    documents = await registry.fetch_all(company)
    record, usages = await assess_company_transition_plan(
        company, documents=documents, llm=llm, fuzzy_threshold=settings.grounding_fuzzy_threshold
    )
    return TransitionPlanAssessmentResult(record, combine_usage(*usages) if usages else LLMUsage())


def create_transition_plan_run(companies: list[CompanyRef], settings: Settings, run_store: RunStore) -> str:
    job_manager = JobManager(run_store)
    manifest = job_manager.create_run("transition_plan", {}, len(companies), model=settings.llm_model)
    return manifest.run_id


async def execute_transition_plan_run(
    run_id: str,
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
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
        result = await _assess_company(company, registry=registry, llm=llm, settings=settings)
        result.record.run_id = run_id
        return result

    await run_company_batch(
        run_id,
        companies,
        run_store=run_store,
        worker=_worker,
        result_to_json=lambda r: r.record.model_dump(mode="json"),
        review_items=lambda c, r: [(c.company_id, r.record.model_dump(mode="json"))] if r.record.needs_review else [],
        cost_usd=lambda r: estimate_cost_usd(settings.llm_model, r.usage),
        concurrency=settings.max_concurrent_llm_calls,
    )
    return run_id


async def run_transition_plan_assessment(
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
) -> str:
    """Convenience wrapper (create + execute in one call) for synchronous
    callers such as the CLI, where blocking until completion is expected."""
    run_id = create_transition_plan_run(companies, settings, run_store)
    return await execute_transition_plan_run(
        run_id, companies, llm=llm, registry=registry, settings=settings, run_store=run_store
    )
