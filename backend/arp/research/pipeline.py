from __future__ import annotations

import json
import logging
from pathlib import Path

from arp.config import Settings
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
from arp.research.revenue_exposure.catalogue import by_company as catalogue_by_company, load_catalogue
from arp.research.revenue_exposure.resolver import RevenueResolverContext
from arp.schemas.common import CompanyRef, JobStatus
from arp.schemas.revenue_exposure import ActivityCatalogueMapping
from arp.schemas.thematic import CompanyMatch, ThemeDefinition
from arp.storage.run_store import RunStore
from arp.universe import load_company_universe

logger = logging.getLogger(__name__)


class CompanyMatchesResult:
    def __init__(self, matches: list[CompanyMatch], usage: LLMUsage) -> None:
        self.matches = matches
        self.usage = usage


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
        match, activity_usages = await match_company_activity(
            company,
            activity,
            documents=documents,
            documents_by_id=documents_by_id,
            llm=llm,
            settings=settings,
            indirect_model=indirect_model,
            revenue_resolver=revenue_resolver,
            company_isic=company_isic,
        )
        matches.append(match)
        usages.extend(activity_usages)

    return CompanyMatchesResult(matches, combine_usage(*usages) if usages else LLMUsage())


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
) -> str:
    """Creates the run manifest synchronously (fast, file-only) so an API
    caller gets a run_id back immediately; execute_theme_run does the actual
    (potentially long-running) work and can be scheduled in the background.

    The resume-relevant inputs (`universe_path`, `use_sample_icio`,
    `use_sample_exiobase`, `revenue_catalogue_path`, `catalogue_mapping`)
    are persisted alongside the manifest -- not needed to *start* a run,
    but what `resume_theme_run` reads back to reconstruct and re-invoke
    `execute_theme_run` for a run that was interrupted, failed, or
    explicitly cancelled.
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
    use_sample_exiobase: bool = False,
    revenue_catalogue_path: str | None = None,
    catalogue_mapping: list[ActivityCatalogueMapping] | None = None,
) -> str:
    """Convenience wrapper (create + execute in one call) for synchronous
    callers such as the CLI, where blocking until completion is expected.

    The `universe_path`/`use_sample_icio`/`use_sample_exiobase`/
    `revenue_catalogue_path`/`catalogue_mapping` params are passed straight
    through to create_theme_run purely so the resulting run is resumable
    via `resume_theme_run` later -- they don't affect this call's own
    behavior (the already-built `indirect_model`/`revenue_resolver` are
    what's actually used to execute it).
    """
    run_id = create_theme_run(
        theme, companies, settings, run_store,
        universe_path=universe_path, use_sample_icio=use_sample_icio, use_sample_exiobase=use_sample_exiobase,
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
