from __future__ import annotations

import logging

from arp.config import Settings
from arp.grounding import ground_citations
from arp.ingestion.parsing import chunk_document
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.batch_runner import run_batch
from arp.orchestration.cost_tracker import combine_usage, estimate_cost_usd
from arp.orchestration.job_manager import JobManager
from arp.orchestration.review_queue import queue_for_review
from arp.research.candidate_sourcer import prefilter_chunks_for_activity
from arp.research.matcher_agents import run_adjudicator, run_advocate, run_opposing
from arp.schemas.common import CompanyRef
from arp.schemas.thematic import AgentOpinion, CompanyMatch, ExposureEstimate, MatchVerdict, ThemeDefinition
from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)

_MAX_EVIDENCE_CHUNKS_PER_CALL = 12


class CompanyMatchesResult:
    def __init__(self, matches: list[CompanyMatch], usage: LLMUsage) -> None:
        self.matches = matches
        self.usage = usage


def _no_evidence_opinion() -> AgentOpinion:
    return AgentOpinion(
        stance="No evidence found",
        rationale="No document chunks matched this activity's seed keywords in the available disclosures.",
        citations=[],
        exposure_estimate=ExposureEstimate.NONE,
    )


async def _match_company(
    company: CompanyRef,
    theme: ThemeDefinition,
    *,
    registry: DocumentSourceRegistry,
    llm: LLMClient,
    settings: Settings,
) -> CompanyMatchesResult:
    documents = await registry.fetch_all(company)
    documents_by_id = {d.doc_id: d for d in documents}
    usages: list[LLMUsage] = []
    matches: list[CompanyMatch] = []

    for activity in theme.activities:
        all_chunks = []
        for doc in documents:
            all_chunks.extend(chunk_document(doc, keywords=activity.seed_keywords))
        evidence = prefilter_chunks_for_activity(all_chunks, activity)

        if not evidence:
            matches.append(
                CompanyMatch(
                    company_id=company.company_id,
                    ticker=company.ticker,
                    name=company.name,
                    activity_id=activity.activity_id,
                    activity_name=activity.name,
                    verdict=MatchVerdict.EXCLUDE,
                    exposure_estimate=ExposureEstimate.NONE,
                    confidence=1.0,
                    advocate=_no_evidence_opinion(),
                    opposing=_no_evidence_opinion(),
                    adjudicator_rationale="No evidence of this activity was found in the available documents.",
                    citations=[],
                    flagged_for_review=False,
                )
            )
            continue

        evidence = evidence[:_MAX_EVIDENCE_CHUNKS_PER_CALL]

        advocate, u1 = await run_advocate(company.name, activity, evidence, llm)
        opposing, u2 = await run_opposing(company.name, activity, evidence, advocate, llm)
        adjudication, u3 = await run_adjudicator(company.name, activity, advocate, opposing, llm)
        usages.extend([u1, u2, u3])

        grounded_citations = ground_citations(
            adjudication.citations, documents_by_id, settings.grounding_fuzzy_threshold
        )
        all_grounded = all(c.grounded for c in grounded_citations) if grounded_citations else False
        flagged = (
            adjudication.verdict == MatchVerdict.UNCERTAIN
            or adjudication.confidence < settings.confidence_review_threshold
            or (adjudication.verdict == MatchVerdict.INCLUDE and not all_grounded)
        )

        matches.append(
            CompanyMatch(
                company_id=company.company_id,
                ticker=company.ticker,
                name=company.name,
                activity_id=activity.activity_id,
                activity_name=activity.name,
                verdict=adjudication.verdict,
                exposure_estimate=adjudication.exposure_estimate,
                confidence=adjudication.confidence,
                advocate=advocate,
                opposing=opposing,
                adjudicator_rationale=adjudication.adjudicator_rationale,
                citations=grounded_citations,
                flagged_for_review=flagged,
            )
        )

    return CompanyMatchesResult(matches, combine_usage(*usages) if usages else LLMUsage())


def create_theme_run(theme: ThemeDefinition, companies: list[CompanyRef], settings: Settings, run_store: RunStore) -> str:
    """Creates the run manifest synchronously (fast, file-only) so an API
    caller gets a run_id back immediately; execute_theme_run does the actual
    (potentially long-running) work and can be scheduled in the background.
    """
    job_manager = JobManager(run_store)
    manifest = job_manager.create_run(
        "theme",
        {"theme_id": theme.theme_id, "theme_name": theme.name},
        len(companies),
        model=settings.llm_model,
    )
    (run_store.run_dir(manifest.run_id) / "theme.json").write_text(theme.model_dump_json(indent=2))
    return manifest.run_id


async def execute_theme_run(
    run_id: str,
    theme: ThemeDefinition,
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
) -> str:
    """Orchestrates the Advocate/Opposing/Adjudicator pipeline across the
    whole company universe for every activity in the theme, with
    checkpointed, resumable, bounded-concurrency execution against an
    already-created run (see create_theme_run).
    """
    job_manager = JobManager(run_store)

    def _on_success(company: CompanyRef, result: CompanyMatchesResult) -> None:
        for match in result.matches:
            if match.flagged_for_review:
                queue_for_review(
                    run_store,
                    run_id,
                    f"{company.company_id}:{match.activity_id}",
                    match.model_dump(mode="json"),
                )
        cost = estimate_cost_usd(settings.llm_model, result.usage)
        job_manager.record_progress(
            run_id,
            completed_delta=1,
            review_delta=sum(1 for m in result.matches if m.flagged_for_review),
            input_tokens_delta=result.usage.input_tokens,
            output_tokens_delta=result.usage.output_tokens,
            cost_delta_usd=cost,
        )

    def _on_error(company: CompanyRef, exc: Exception) -> None:
        job_manager.record_progress(run_id, failed_delta=1)

    await run_batch(
        companies,
        item_key=lambda c: c.company_id,
        worker=lambda c: _match_company(c, theme, registry=registry, llm=llm, settings=settings),
        results_path=run_store.results_path(run_id),
        errors_path=run_store.errors_path(run_id),
        concurrency=settings.max_concurrent_llm_calls,
        result_to_json=lambda r: {"company_matches": [m.model_dump(mode="json") for m in r.matches]},
        on_success=_on_success,
        on_error=_on_error,
    )

    job_manager.finish_run(run_id)
    return run_id


async def run_thematic_universe(
    theme: ThemeDefinition,
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
) -> str:
    """Convenience wrapper (create + execute in one call) for synchronous
    callers such as the CLI, where blocking until completion is expected."""
    run_id = create_theme_run(theme, companies, settings, run_store)
    return await execute_theme_run(
        run_id, theme, companies, llm=llm, registry=registry, settings=settings, run_store=run_store
    )
