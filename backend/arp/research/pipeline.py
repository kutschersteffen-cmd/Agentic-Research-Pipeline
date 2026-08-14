from __future__ import annotations

import json
import logging
from pathlib import Path

from arp.config import Settings
from arp.grounding import ground_citations
from arp.ingestion.parsing import chunk_document
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.batch_runner import run_batch
from arp.orchestration.cost_tracker import combine_usage, estimate_cost_usd
from arp.orchestration.job_manager import JobManager
from arp.orchestration.review_queue import queue_for_review
from arp.research.indirect_exposure.company_mapper import resolve_company_isic
from arp.research.indirect_exposure.exposure import compute_indirect_exposure
from arp.research.indirect_exposure.factory import build_leontief_model
from arp.research.indirect_exposure.leontief import LeontiefModel
from arp.research.matcher_agents import run_adjudicator, run_advocate, run_opposing
from arp.research.revenue_exposure.catalogue import by_company as catalogue_by_company, load_catalogue
from arp.research.revenue_exposure.resolver import RevenueResolverContext, band_exposure, resolve_company_activity_exposure
from arp.retrieval.select_evidence import select_relevant_chunks
from arp.schemas.common import CompanyRef, JobStatus
from arp.schemas.revenue_exposure import ActivityCatalogueMapping
from arp.schemas.thematic import AgentOpinion, CompanyMatch, ExposureEstimate, MatchVerdict, ThemeDefinition
from arp.storage.run_store import RunStore
from arp.universe import load_company_universe

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
    indirect_model: LeontiefModel | None = None,
    revenue_resolver: RevenueResolverContext | None = None,
) -> CompanyMatchesResult:
    documents = await registry.fetch_all(company)
    documents_by_id = {d.doc_id: d for d in documents}
    usages: list[LLMUsage] = []
    matches: list[CompanyMatch] = []

    # Resolved once per company (not per activity) since it's the same
    # answer regardless of which activity is being screened. Reused for
    # both the indirect-exposure tier and the revenue-exposure resolver's
    # sector-relevance gate, so enabling one doesn't force a second,
    # redundant classification call if the other later gets enabled too.
    company_isic: str | None = None
    isic_model = indirect_model or (revenue_resolver.isic_model if revenue_resolver else None)
    if isic_model is not None:
        company_isic, u_isic = await resolve_company_isic(company, isic_model, llm)
        usages.append(u_isic)

    for activity in theme.activities:
        indirect = None
        if indirect_model is not None and company_isic and activity.core_isic_codes:
            indirect = compute_indirect_exposure(
                company.company_id, company_isic, indirect_model, set(activity.core_isic_codes), indirect_model.edition_label
            )

        if revenue_resolver is not None:
            revenue_exposure, u_rev = await resolve_company_activity_exposure(
                company, activity, company_isic, documents=documents, ctx=revenue_resolver, llm=llm
            )
            usages.append(u_rev)

            if revenue_exposure.revenue.value_pct is not None:
                # Path 1 (catalogue) or path 2 (extraction) resolved a hard
                # number -- the qualitative debate (path 3) is skipped
                # entirely for this pair, both for cost and because a real
                # disclosed/extracted figure shouldn't be second-guessed by
                # a categorical LLM judgment over the same question.
                revenue = revenue_exposure.revenue
                banded = band_exposure(revenue.value_pct, settings)
                verdict = MatchVerdict.EXCLUDE if banded == ExposureEstimate.NONE else MatchVerdict.INCLUDE
                source_desc = "structured revenue catalogue" if revenue.source == "catalogue" else "an extracted, grounded disclosure figure"
                rationale = f"Resolved via {source_desc}: {revenue.value_pct:.1%} of revenue attributed to this activity. {revenue.notes}".strip()
                citations = [revenue.citation] if revenue.citation else []
                ungrounded = revenue.citation is not None and not revenue.citation.grounded
                flagged = revenue.source == "extracted" and (revenue.confidence < settings.confidence_review_threshold or ungrounded)

                matches.append(
                    CompanyMatch(
                        company_id=company.company_id,
                        ticker=company.ticker,
                        name=company.name,
                        activity_id=activity.activity_id,
                        activity_name=activity.name,
                        verdict=verdict,
                        exposure_estimate=banded,
                        confidence=revenue.confidence,
                        adjudicator_rationale=rationale,
                        citations=citations,
                        indirect_exposure=indirect,
                        revenue_exposure=revenue_exposure,
                        flagged_for_review=flagged,
                    )
                )
                continue
        else:
            revenue_exposure = None

        all_chunks = []
        for doc in documents:
            all_chunks.extend(chunk_document(doc, keywords=activity.seed_keywords))
        evidence = select_relevant_chunks(all_chunks, activity.seed_keywords, max_chunks=_MAX_EVIDENCE_CHUNKS_PER_CALL)

        if not evidence:
            structural_flag = bool(
                indirect
                and max(indirect.upstream_exposure, indirect.downstream_exposure)
                >= settings.indirect_exposure_review_threshold
            )
            rationale = "No evidence of this activity was found in the available documents."
            if structural_flag:
                rationale += (
                    " However, input-output propagation shows structural exposure to this activity's core "
                    "sectors above the review threshold -- routed for a second look rather than excluded outright."
                )
            matches.append(
                CompanyMatch(
                    company_id=company.company_id,
                    ticker=company.ticker,
                    name=company.name,
                    activity_id=activity.activity_id,
                    activity_name=activity.name,
                    verdict=MatchVerdict.EXCLUDE,
                    exposure_estimate=ExposureEstimate.NONE,
                    confidence=0.5 if structural_flag else 1.0,
                    advocate=_no_evidence_opinion(),
                    opposing=_no_evidence_opinion(),
                    adjudicator_rationale=rationale,
                    citations=[],
                    indirect_exposure=indirect,
                    revenue_exposure=revenue_exposure,
                    flagged_for_review=structural_flag,
                )
            )
            continue

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
                indirect_exposure=indirect,
                revenue_exposure=revenue_exposure,
                flagged_for_review=flagged,
            )
        )

    return CompanyMatchesResult(matches, combine_usage(*usages) if usages else LLMUsage())


def create_theme_run(
    theme: ThemeDefinition,
    companies: list[CompanyRef],
    settings: Settings,
    run_store: RunStore,
    *,
    universe_path: str | None = None,
    use_sample_icio: bool = False,
    revenue_catalogue_path: str | None = None,
    catalogue_mapping: list[ActivityCatalogueMapping] | None = None,
) -> str:
    """Creates the run manifest synchronously (fast, file-only) so an API
    caller gets a run_id back immediately; execute_theme_run does the actual
    (potentially long-running) work and can be scheduled in the background.

    The resume-relevant inputs (`universe_path`, `use_sample_icio`,
    `revenue_catalogue_path`, `catalogue_mapping`) are persisted alongside
    the manifest -- not needed to *start* a run, but what `resume_theme_run`
    reads back to reconstruct and re-invoke `execute_theme_run` for a run
    that was interrupted, failed, or explicitly cancelled.
    """
    job_manager = JobManager(run_store)
    manifest = job_manager.create_run(
        "theme",
        {
            "theme_id": theme.theme_id,
            "theme_name": theme.name,
            "universe_path": universe_path,
            "use_sample_icio": use_sample_icio,
            "revenue_catalogue_path": revenue_catalogue_path,
        },
        len(companies),
        model=settings.llm_model,
    )
    run_dir = run_store.run_dir(manifest.run_id)
    (run_dir / "theme.json").write_text(theme.model_dump_json(indent=2))
    if catalogue_mapping:
        (run_dir / "catalogue_mapping.json").write_text(json.dumps([m.model_dump(mode="json") for m in catalogue_mapping], indent=2))
    return manifest.run_id


async def resume_theme_run(run_id: str, *, llm: LLMClient, registry: DocumentSourceRegistry, settings: Settings, run_store: RunStore) -> str:
    """Reconstructs and re-invokes execute_theme_run for an existing run_id
    -- for a run interrupted mid-batch (process restart), one that ended
    PARTIALLY_COMPLETED/FAILED, or one the user cancelled and wants to
    continue. Nothing is redone: run_batch's own resumability (skipping
    item keys already in results.jsonl) picks up exactly where the run
    left off.
    """
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise ValueError(f"Unknown run_id: {run_id}")
    if manifest.run_type != "theme":
        raise ValueError(f"Run {run_id} is a {manifest.run_type} run, not a theme run.")
    universe_path = manifest.params.get("universe_path")
    if not universe_path:
        raise ValueError(f"Run {run_id} has no stored universe_path -- it predates resume support and can't be reconstructed.")

    run_dir = run_store.run_dir(run_id)
    theme = ThemeDefinition.model_validate_json((run_dir / "theme.json").read_text())
    companies = load_company_universe(universe_path)

    indirect_model = build_leontief_model(settings, use_sample=bool(manifest.params.get("use_sample_icio")))
    revenue_resolver = None
    revenue_catalogue_path = manifest.params.get("revenue_catalogue_path")
    if revenue_catalogue_path:
        mapping_path = run_dir / "catalogue_mapping.json"
        mappings = [ActivityCatalogueMapping.model_validate(m) for m in json.loads(mapping_path.read_text())] if mapping_path.exists() else []
        revenue_resolver = RevenueResolverContext(
            catalogue_by_company=catalogue_by_company(load_catalogue(Path(revenue_catalogue_path))),
            mappings=mappings, registry=registry, settings=settings, isic_model=indirect_model,
        )

    manifest.cancel_requested = False
    manifest.status = JobStatus.RUNNING
    run_store.save_manifest(manifest)

    return await execute_theme_run(
        run_id, theme, companies, llm=llm, registry=registry, settings=settings, run_store=run_store,
        indirect_model=indirect_model, revenue_resolver=revenue_resolver,
    )


async def execute_theme_run(
    run_id: str,
    theme: ThemeDefinition,
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
    indirect_model: LeontiefModel | None = None,
    revenue_resolver: RevenueResolverContext | None = None,
) -> str:
    """Orchestrates the Advocate/Opposing/Adjudicator pipeline across the
    whole company universe for every activity in the theme, with
    checkpointed, resumable, bounded-concurrency execution against an
    already-created run (see create_theme_run).

    `indirect_model`, if supplied, additionally computes an input-output
    structural exposure score per (company, activity) -- see
    arp/research/indirect_exposure/. Off by default.

    `revenue_resolver`, if supplied, resolves each (company, activity)
    pair's exposure via structured revenue/capex data first (catalogue,
    then extraction from disclosures), falling back to the qualitative
    debate only where both miss -- see arp/research/revenue_exposure/.
    Off by default; existing behavior is unchanged when None.
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

    def _cancel_check() -> bool:
        current = run_store.load_manifest(run_id)
        return current is not None and current.cancel_requested

    await run_batch(
        companies,
        item_key=lambda c: c.company_id,
        worker=lambda c: _match_company(
            c, theme, registry=registry, llm=llm, settings=settings, indirect_model=indirect_model, revenue_resolver=revenue_resolver
        ),
        results_path=run_store.results_path(run_id),
        errors_path=run_store.errors_path(run_id),
        concurrency=settings.max_concurrent_llm_calls,
        result_to_json=lambda r: {"company_matches": [m.model_dump(mode="json") for m in r.matches]},
        on_success=_on_success,
        on_error=_on_error,
        cancel_check=_cancel_check,
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
    indirect_model: LeontiefModel | None = None,
    revenue_resolver: RevenueResolverContext | None = None,
    universe_path: str | None = None,
    use_sample_icio: bool = False,
    revenue_catalogue_path: str | None = None,
    catalogue_mapping: list[ActivityCatalogueMapping] | None = None,
) -> str:
    """Convenience wrapper (create + execute in one call) for synchronous
    callers such as the CLI, where blocking until completion is expected.

    The `universe_path`/`use_sample_icio`/`revenue_catalogue_path`/
    `catalogue_mapping` params are passed straight through to
    create_theme_run purely so the resulting run is resumable via
    `resume_theme_run` later -- they don't affect this call's own
    behavior (the already-built `indirect_model`/`revenue_resolver` are
    what's actually used to execute it).
    """
    run_id = create_theme_run(
        theme, companies, settings, run_store,
        universe_path=universe_path, use_sample_icio=use_sample_icio,
        revenue_catalogue_path=revenue_catalogue_path, catalogue_mapping=catalogue_mapping,
    )
    return await execute_theme_run(
        run_id,
        theme,
        companies,
        llm=llm,
        registry=registry,
        settings=settings,
        run_store=run_store,
        indirect_model=indirect_model,
        revenue_resolver=revenue_resolver,
    )
