from __future__ import annotations

import json
import logging
from pathlib import Path

from arp.config import Settings
from arp.discovery.site_finder import DuckDuckGoSearchClient
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.batch_runner import run_batch
from arp.orchestration.cost_tracker import combine_usage, estimate_cost_usd
from arp.orchestration.job_manager import JobManager
from arp.orchestration.review_queue import queue_for_review
from arp.research.indirect_exposure.company_mapper import resolve_company_isic
from arp.research.indirect_exposure.factory import resolve_indirect_exposure_model
from arp.research.indirect_exposure.leontief import LeontiefModel
from arp.research.match_graph import match_company_activity
from arp.research.rd_exposure.resolver import RDResolverContext
from arp.research.revenue_exposure.catalogue import by_company as catalogue_by_company, load_catalogue
from arp.research.revenue_exposure.resolver import RevenueResolverContext
from arp.schemas.common import CompanyRef, JobStatus
from arp.schemas.revenue_exposure import ActivityCatalogueMapping
from arp.schemas.thematic import CompanyMatch, ThemeDefinition
from arp.storage.run_store import RunStore
from arp.universe import load_company_universe

logger = logging.getLogger(__name__)


class CompanyMatchesResult:
    def __init__(self, matches: list[CompanyMatch], usage: LLMUsage, cost_usd: float) -> None:
        self.matches = matches
        self.usage = usage
        self.cost_usd = cost_usd


async def _match_company(
    company: CompanyRef,
    theme: ThemeDefinition,
    *,
    registry: DocumentSourceRegistry,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    settings: Settings,
    indirect_model: LeontiefModel | None = None,
    revenue_resolver: RevenueResolverContext | None = None,
    rd_resolver: RDResolverContext | None = None,
) -> CompanyMatchesResult:
    documents = await registry.fetch_all(company)
    documents_by_id = {d.doc_id: d for d in documents}
    usages: list[LLMUsage] = []
    matches: list[CompanyMatch] = []

    # Resolved once per company (not per activity) since it's the same
    # answer regardless of which activity is being screened. Reused across
    # the indirect-exposure tier, the revenue-exposure resolver's, and the
    # rd-exposure resolver's sector-relevance gates, so enabling more than
    # one doesn't force a redundant classification call.
    company_isic: str | None = None
    isic_model = indirect_model or (revenue_resolver.isic_model if revenue_resolver else None) or (rd_resolver.isic_model if rd_resolver else None)
    if isic_model is not None:
        company_isic, u_isic = await resolve_company_isic(company, isic_model, llm)
        usages.append(u_isic)

    for activity in theme.activities:
        match, activity_usages = await match_company_activity(
            company,
            activity,
            documents=documents,
            documents_by_id=documents_by_id,
            llm=llm,
            verifier_llm=verifier_llm,
            settings=settings,
            indirect_model=indirect_model,
            revenue_resolver=revenue_resolver,
            rd_resolver=rd_resolver,
            company_isic=company_isic,
        )
        matches.append(match)
        usages.extend(activity_usages)

    # Per-usage-model cost (see extraction/pipeline.py for the same fix):
    # usages can now mix llm_model (Advocate/Opposing/Adjudicator, ISIC
    # resolution) and llm_verifier_model (the revenue-exposure resolver's
    # path-2 extraction fallback) calls within one company.
    cost = sum(estimate_cost_usd(u.model or settings.llm_model, u) for u in usages)
    return CompanyMatchesResult(matches, combine_usage(*usages) if usages else LLMUsage(), cost)


def create_theme_run(
    theme: ThemeDefinition,
    companies: list[CompanyRef],
    settings: Settings,
    run_store: RunStore,
    *,
    universe_path: str | None = None,
    use_sample_icio: bool = False,
    use_sample_exiobase: bool = False,
    revenue_catalogue_path: str | None = None,
    catalogue_mapping: list[ActivityCatalogueMapping] | None = None,
    enable_rd_exposure: bool = False,
) -> str:
    """Creates the run manifest synchronously (fast, file-only) so an API
    caller gets a run_id back immediately; execute_theme_run does the actual
    (potentially long-running) work and can be scheduled in the background.

    The resume-relevant inputs (`universe_path`, `use_sample_icio`,
    `use_sample_exiobase`, `revenue_catalogue_path`, `catalogue_mapping`,
    `enable_rd_exposure`) are persisted alongside the manifest -- not
    needed to *start* a run, but what `resume_theme_run` reads back to
    reconstruct and re-invoke `execute_theme_run` for a run that was
    interrupted, failed, or explicitly cancelled.
    """
    job_manager = JobManager(run_store)
    manifest = job_manager.create_run(
        "theme",
        {
            "theme_id": theme.theme_id,
            "theme_name": theme.name,
            "universe_path": universe_path,
            "use_sample_icio": use_sample_icio,
            "use_sample_exiobase": use_sample_exiobase,
            "revenue_catalogue_path": revenue_catalogue_path,
            "enable_rd_exposure": enable_rd_exposure,
        },
        len(companies),
        model=settings.llm_model,
        verifier_model=settings.llm_verifier_model,
    )
    run_dir = run_store.run_dir(manifest.run_id)
    (run_dir / "theme.json").write_text(theme.model_dump_json(indent=2))
    if catalogue_mapping:
        (run_dir / "catalogue_mapping.json").write_text(json.dumps([m.model_dump(mode="json") for m in catalogue_mapping], indent=2))
    return manifest.run_id


async def resume_theme_run(
    run_id: str,
    *,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
) -> str:
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

    indirect_model = resolve_indirect_exposure_model(
        settings,
        use_sample_icio=bool(manifest.params.get("use_sample_icio")),
        use_sample_exiobase=bool(manifest.params.get("use_sample_exiobase")),
    )
    revenue_resolver = None
    revenue_catalogue_path = manifest.params.get("revenue_catalogue_path")
    if revenue_catalogue_path:
        mapping_path = run_dir / "catalogue_mapping.json"
        mappings = [ActivityCatalogueMapping.model_validate(m) for m in json.loads(mapping_path.read_text())] if mapping_path.exists() else []
        revenue_resolver = RevenueResolverContext(
            catalogue_by_company=catalogue_by_company(load_catalogue(Path(revenue_catalogue_path))),
            mappings=mappings, registry=registry, settings=settings, isic_model=indirect_model,
        )

    rd_resolver = None
    if manifest.params.get("enable_rd_exposure"):
        rd_resolver = RDResolverContext(
            registry=registry, settings=settings, isic_model=indirect_model,
            search_client=DuckDuckGoSearchClient(settings.discovery_user_agent),
        )

    manifest.cancel_requested = False
    manifest.status = JobStatus.RUNNING
    run_store.save_manifest(manifest)

    return await execute_theme_run(
        run_id, theme, companies, llm=llm, verifier_llm=verifier_llm, registry=registry, settings=settings, run_store=run_store,
        indirect_model=indirect_model, revenue_resolver=revenue_resolver, rd_resolver=rd_resolver,
    )


async def execute_theme_run(
    run_id: str,
    theme: ThemeDefinition,
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
    indirect_model: LeontiefModel | None = None,
    revenue_resolver: RevenueResolverContext | None = None,
    rd_resolver: RDResolverContext | None = None,
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

    `rd_resolver`, if supplied, additionally resolves an R&D-spend-
    intensity + news-mention signal (Method C) for pre-revenue/emerging
    activities (lifecycle_stage ideation/innovation) -- see
    arp/research/rd_exposure/. Never short-circuits the debate the way a
    resolved revenue number does; off by default.
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
        job_manager.record_progress(
            run_id,
            completed_delta=1,
            review_delta=sum(1 for m in result.matches if m.flagged_for_review),
            input_tokens_delta=result.usage.input_tokens,
            output_tokens_delta=result.usage.output_tokens,
            cost_delta_usd=result.cost_usd,
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
            c,
            theme,
            registry=registry,
            llm=llm,
            verifier_llm=verifier_llm,
            settings=settings,
            indirect_model=indirect_model,
            revenue_resolver=revenue_resolver,
            rd_resolver=rd_resolver,
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
    verifier_llm: LLMClient | None = None,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
    indirect_model: LeontiefModel | None = None,
    revenue_resolver: RevenueResolverContext | None = None,
    rd_resolver: RDResolverContext | None = None,
    universe_path: str | None = None,
    use_sample_icio: bool = False,
    use_sample_exiobase: bool = False,
    revenue_catalogue_path: str | None = None,
    catalogue_mapping: list[ActivityCatalogueMapping] | None = None,
    enable_rd_exposure: bool = False,
) -> str:
    """Convenience wrapper (create + execute in one call) for synchronous
    callers such as the CLI, where blocking until completion is expected.

    The `universe_path`/`use_sample_icio`/`use_sample_exiobase`/
    `revenue_catalogue_path`/`catalogue_mapping`/`enable_rd_exposure`
    params are passed straight through to create_theme_run purely so the
    resulting run is resumable via `resume_theme_run` later -- they don't
    affect this call's own behavior (the already-built
    `indirect_model`/`revenue_resolver`/`rd_resolver` are what's actually
    used to execute it).
    """
    run_id = create_theme_run(
        theme, companies, settings, run_store,
        universe_path=universe_path, use_sample_icio=use_sample_icio, use_sample_exiobase=use_sample_exiobase,
        revenue_catalogue_path=revenue_catalogue_path, catalogue_mapping=catalogue_mapping,
        enable_rd_exposure=enable_rd_exposure,
    )
    return await execute_theme_run(
        run_id,
        theme,
        companies,
        llm=llm,
        verifier_llm=verifier_llm,
        registry=registry,
        settings=settings,
        run_store=run_store,
        indirect_model=indirect_model,
        revenue_resolver=revenue_resolver,
        rd_resolver=rd_resolver,
    )


def load_theme_run_matches(run_store: RunStore, run_id: str) -> list[CompanyMatch] | None:
    """Loads and flattens every CompanyMatch persisted for a theme run --
    each results.jsonl row is one company's `{"company_matches": [...]}`
    (see execute_theme_run's result_to_json above), not a flat per-match
    row, so this is the one place that flattening happens rather than
    every consumer (CSV/XLSX export, the results-diff feature, the ranked-
    results endpoint) reimplementing it. Returns None if the run doesn't
    exist or isn't a theme run.
    """
    manifest = run_store.load_manifest(run_id)
    if manifest is None or manifest.run_type != "theme":
        return None
    rows = run_store.read_jsonl(run_store.results_path(run_id))
    return [CompanyMatch.model_validate(m) for row in rows for m in row.get("company_matches", [])]


def rank_theme_matches(matches: list[CompanyMatch]) -> list[CompanyMatch]:
    """Sorts matches by arbitration.composite_score descending -- the
    ranked-list output the spec calls for (Step 5), layered on top of
    arbitration's own "additional signal, never blended" design: this only
    orders the existing matches, it doesn't alter any of their fields.
    Matches with no arbitration result (shouldn't happen in practice, since
    match_graph.py always computes one) sort last, not first.
    """
    return sorted(matches, key=lambda m: m.arbitration.composite_score if m.arbitration else -1.0, reverse=True)
