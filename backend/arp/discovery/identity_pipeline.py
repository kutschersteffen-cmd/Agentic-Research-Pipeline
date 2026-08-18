from __future__ import annotations

import logging

from arp.config import Settings
from arp.discovery.identity_graph import resolve_company_identity
from arp.discovery.site_finder import DuckDuckGoSearchClient, WebSearchClient
from arp.ingestion.edgar import EdgarDocumentSource
from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.batch_runner import run_batch
from arp.orchestration.cost_tracker import combine_usage, estimate_cost_usd
from arp.orchestration.job_manager import JobManager
from arp.orchestration.review_queue import latest_decisions, queue_for_review
from arp.schemas.common import CompanyRef
from arp.schemas.discovery import IdentityResolutionResult, IdentityVerdict
from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)


class IdentityResolutionOutcome:
    def __init__(self, result: IdentityResolutionResult, usage: LLMUsage) -> None:
        self.result = result
        self.usage = usage


def create_identity_run(companies: list[CompanyRef], run_store: RunStore) -> str:
    job_manager = JobManager(run_store)
    manifest = job_manager.create_run("identity", {"company_count": len(companies)}, len(companies))
    return manifest.run_id


async def execute_identity_run(
    run_id: str,
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    settings: Settings,
    run_store: RunStore,
    edgar: EdgarDocumentSource | None = None,
    search_client: WebSearchClient | None = None,
) -> str:
    """Resolves each company's real-world identity (website/CIK) via the
    propose -> resolve -> challenge -> adjudicate graph
    (arp/discovery/identity_graph.py), with checkpointed, resumable,
    bounded-concurrency execution -- the same run_batch shape every other
    pipeline in this app uses. A company that already supplies website/cik
    resolves for free (zero LLM calls, see identity_graph.py).

    Deliberately does not touch arp/discovery/pipeline.py or the crawl/
    download code at all: a RESOLVED, non-flagged company's website/cik is
    only usable once exported via enriched_universe() below and fed into
    the *existing* discovery run as an ordinary universe file. This keeps
    the (LLM-cost-bearing) identity resolution step a one-time cost per
    company, not something paid again on every discovery run.
    """
    job_manager = JobManager(run_store)
    edgar = edgar or EdgarDocumentSource(settings.edgar_user_agent, settings.cache_dir)
    search_client = search_client or DuckDuckGoSearchClient(settings.discovery_user_agent)

    async def _resolve_one(company: CompanyRef) -> IdentityResolutionOutcome:
        result, usages = await resolve_company_identity(
            company,
            llm=llm,
            edgar=edgar,
            search_client=search_client,
            max_search_results=settings.identity_resolution_max_search_results,
            confidence_threshold=settings.identity_resolution_confidence_threshold,
        )
        return IdentityResolutionOutcome(result, combine_usage(*usages) if usages else LLMUsage())

    def _on_success(company: CompanyRef, outcome: IdentityResolutionOutcome) -> None:
        if outcome.result.flagged_for_review:
            queue_for_review(run_store, run_id, company.company_id, outcome.result.model_dump(mode="json"))
        cost = estimate_cost_usd(settings.llm_model, outcome.usage)
        job_manager.record_progress(
            run_id,
            completed_delta=1,
            review_delta=1 if outcome.result.flagged_for_review else 0,
            input_tokens_delta=outcome.usage.input_tokens,
            output_tokens_delta=outcome.usage.output_tokens,
            cost_delta_usd=cost,
        )

    def _on_error(company: CompanyRef, exc: Exception) -> None:
        job_manager.record_progress(run_id, failed_delta=1)

    def _cancel_check() -> bool:
        current = run_store.load_manifest(run_id)
        return current is not None and current.cancel_requested

    await run_batch(
        companies,
        item_key=lambda c: c.company_id,
        worker=_resolve_one,
        results_path=run_store.results_path(run_id),
        errors_path=run_store.errors_path(run_id),
        concurrency=settings.max_concurrent_llm_calls,
        result_to_json=lambda o: o.result.model_dump(mode="json"),
        on_success=_on_success,
        on_error=_on_error,
        cancel_check=_cancel_check,
    )

    job_manager.finish_run(run_id)
    return run_id


async def run_identity_resolution(
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    settings: Settings,
    run_store: RunStore,
    edgar: EdgarDocumentSource | None = None,
    search_client: WebSearchClient | None = None,
) -> str:
    """Convenience wrapper (create + execute in one call) for synchronous
    callers such as the CLI."""
    run_id = create_identity_run(companies, run_store)
    return await execute_identity_run(
        run_id, companies, llm=llm, settings=settings, run_store=run_store, edgar=edgar, search_client=search_client
    )


def enriched_universe(run_store: RunStore, run_id: str) -> list[CompanyRef]:
    """Merges the run's results with any recorded review decisions
    (arp.orchestration.review_queue) into a normal company universe
    (website/cik filled in) -- directly usable as input to the *existing*,
    unmodified discovery pipeline (same shape arp.universe.load_company_universe
    reads). An approved/edited review decision's edited_value overrides the
    agent's own resolved fields and always includes the company; a
    rejected decision excludes it; a still-flagged company with no
    decision yet is excluded rather than emitted with an unverified or
    missing website/cik.
    """
    rows = run_store.read_jsonl(run_store.results_path(run_id))
    decisions = latest_decisions(run_store, run_id)
    companies: list[CompanyRef] = []
    for row in rows:
        result = IdentityResolutionResult.model_validate(row)
        website, cik = result.resolved_website, result.resolved_cik
        included = result.verdict == IdentityVerdict.RESOLVED and not result.flagged_for_review

        decision = decisions.get(result.company_id)
        if decision is not None:
            if decision["decision"] == "reject":
                continue
            edited = decision.get("edited_value") or {}
            website = edited.get("resolved_website", website)
            cik = edited.get("resolved_cik", cik)
            included = decision["decision"] in ("approve", "edit")

        if not included or (not website and not cik):
            continue
        companies.append(CompanyRef(company_id=result.company_id, name=result.input_name, website=website, cik=cik))
    return companies
