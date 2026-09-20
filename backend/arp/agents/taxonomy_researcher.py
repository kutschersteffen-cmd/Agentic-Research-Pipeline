from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from arp.config import Settings
from arp.discovery.site_finder import WebSearchClient
from arp.llm.base import LLMClient
from arp.orchestration.job_manager import JobManager
from arp.research.taxonomy_sources.authority import build_theme_from_authority_sources
from arp.research.taxonomy_sources.compare import merge_taxonomies
from arp.research.taxonomy_sources.discovery import discover_authority_sources, rank_authority_sources
from arp.schemas.taxonomy import DerivationMethod, Taxonomy, TaxonomyStatus
from arp.schemas.taxonomy_researcher import TaxonomyResearcherScheduleConfig, TaxonomyResearchFinding
from arp.schemas.thematic import ThemeDefinition
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore

logger = logging.getLogger(__name__)

_JOB_ID = "taxonomy-researcher-schedule"


async def research_taxonomy(
    taxonomy: Taxonomy, llm: LLMClient, search_client: WebSearchClient, settings: Settings
) -> tuple[TaxonomyResearchFinding, ThemeDefinition | None]:
    """One taxonomy's research pass: re-searches for current authority
    sources (catching documents published/discovered since the taxonomy
    was last derived/ratified), extracts activities from the strongest
    ones, and merges them against the taxonomy's existing activities via
    the same LLM-merge primitive the manual taxonomy-compare/merge feature
    uses. Returns (finding, merged_theme) -- merged_theme is non-None only
    when finding.proposed is True; writing it as a new taxonomy version is
    the caller's job (TaxonomyStore.new_version already always writes
    DRAFT status, so "propose, never auto-apply" is guaranteed by the
    store itself once the caller does that write -- nothing here ratifies
    anything).

    Name-based dedup ("is this activity already in the taxonomy") is
    intentionally coarse (case-insensitive exact name match) -- the real
    semantic dedup/MECE work happens inside merge_taxonomies's own LLM
    merge step; this function's job is only to identify which of the
    merged output's activities are worth reporting as genuinely new.
    """
    candidates = await discover_authority_sources(taxonomy.name, search_client)
    if not candidates:
        return TaxonomyResearchFinding(
            taxonomy_id=taxonomy.taxonomy_id, taxonomy_name=taxonomy.name, proposed=False,
            reason="No candidate authority sources found.",
        ), None

    ranked, _usage = await rank_authority_sources(taxonomy.name, candidates, llm)
    top_urls = [
        c.url for c in ranked[: settings.taxonomy_researcher_max_sources]
        if (c.authority_score or 0.0) >= settings.taxonomy_researcher_min_authority_score
    ]
    if not top_urls:
        return TaxonomyResearchFinding(
            taxonomy_id=taxonomy.taxonomy_id, taxonomy_name=taxonomy.name, proposed=False,
            reason="No sufficiently authoritative sources found.",
        ), None

    try:
        candidate_theme, _notes, _usage = await build_theme_from_authority_sources(
            taxonomy.name, taxonomy.theme.description, top_urls, llm, settings.discovery_user_agent
        )
    except ValueError:
        return TaxonomyResearchFinding(
            taxonomy_id=taxonomy.taxonomy_id, taxonomy_name=taxonomy.name, proposed=False,
            reason="No groundable activities could be extracted from current sources.",
        ), None

    candidate_taxonomy = Taxonomy(name=taxonomy.name, theme=candidate_theme, derivation_method=DerivationMethod.AUTHORITY_SOURCE)
    merged_theme, merge_notes, _usage = await merge_taxonomies(
        [taxonomy, candidate_taxonomy], taxonomy.name, taxonomy.theme.description, llm
    )
    existing_names = {a.name.strip().lower() for a in taxonomy.theme.activities}
    added = [a for a in merged_theme.activities if a.name.strip().lower() not in existing_names]
    if not added:
        return TaxonomyResearchFinding(
            taxonomy_id=taxonomy.taxonomy_id, taxonomy_name=taxonomy.name, proposed=False,
            reason="Re-derivation found nothing beyond the existing taxonomy.",
        ), None

    finding = TaxonomyResearchFinding(
        taxonomy_id=taxonomy.taxonomy_id, taxonomy_name=taxonomy.name, proposed=True,
        added_activity_names=[a.name for a in added], reason=merge_notes,
    )
    return finding, merged_theme


def _ratified_taxonomies(taxonomy_store: TaxonomyStore, taxonomy_ids: list[str] | None) -> list[Taxonomy]:
    ratified = [t for t in taxonomy_store.list_all() if t.status == TaxonomyStatus.RATIFIED]
    if taxonomy_ids is not None:
        wanted = set(taxonomy_ids)
        ratified = [t for t in ratified if t.taxonomy_id in wanted]
    return ratified


def create_taxonomy_research_run(
    taxonomy_store: TaxonomyStore, run_store: RunStore, taxonomy_ids: list[str] | None, triggered_by: str
) -> str:
    """Creates the run manifest synchronously (fast, file-only) so an API
    caller gets a run_id back immediately -- execute_taxonomy_research_run
    does the actual (potentially slow) scanning and can be scheduled in
    the background. Mirrors discovery/pipeline.py's
    create_discovery_run/execute_discovery_run split.
    """
    ratified = _ratified_taxonomies(taxonomy_store, taxonomy_ids)
    job_manager = JobManager(run_store)
    manifest = job_manager.create_run(
        "taxonomy_research", {"triggered_by": triggered_by, "taxonomy_ids": taxonomy_ids}, len(ratified)
    )
    return manifest.run_id


async def execute_taxonomy_research_run(
    run_id: str,
    *,
    llm: LLMClient,
    search_client: WebSearchClient,
    settings: Settings,
    taxonomy_store: TaxonomyStore,
    run_store: RunStore,
    taxonomy_ids: list[str] | None = None,
) -> str:
    """Scans every ratified taxonomy (or just `taxonomy_ids`, if given),
    proposes a new DRAFT version for any that surface genuinely new
    activities, and logs one TaxonomyResearchFinding row per taxonomy
    scanned (proposed or not), against an already-created run (see
    create_taxonomy_research_run).
    """
    ratified = _ratified_taxonomies(taxonomy_store, taxonomy_ids)
    job_manager = JobManager(run_store)

    for taxonomy in ratified:
        try:
            finding, merged_theme = await research_taxonomy(taxonomy, llm, search_client, settings)
            if finding.proposed and merged_theme is not None:
                updated = taxonomy_store.new_version(
                    taxonomy.taxonomy_id, merged_theme, DerivationMethod.MERGED,
                    f"Automated Taxonomy Researcher proposal ({len(finding.added_activity_names)} new "
                    f"activity/activities): {finding.reason}",
                )
                finding = finding.model_copy(update={"new_version": updated.version})
            run_store.append_jsonl(run_store.results_path(run_id), finding.model_dump(mode="json"))
            job_manager.record_progress(run_id, completed_delta=1, review_delta=1 if finding.proposed else 0)
        except Exception:  # noqa: BLE001 - one taxonomy failing must not abort the whole scan
            logger.exception("Taxonomy research failed for taxonomy_id=%s", taxonomy.taxonomy_id)
            job_manager.record_progress(run_id, failed_delta=1)

    job_manager.finish_run(run_id)
    return run_id


async def run_taxonomy_research(
    *,
    llm: LLMClient,
    search_client: WebSearchClient,
    settings: Settings,
    taxonomy_store: TaxonomyStore,
    run_store: RunStore,
    taxonomy_ids: list[str] | None = None,
    triggered_by: str = "manual",
) -> str:
    """Convenience wrapper (create + execute in one call) for the CLI and
    the scheduler, where blocking until completion is expected."""
    run_id = create_taxonomy_research_run(taxonomy_store, run_store, taxonomy_ids, triggered_by)
    return await execute_taxonomy_research_run(
        run_id, llm=llm, search_client=search_client, settings=settings,
        taxonomy_store=taxonomy_store, run_store=run_store, taxonomy_ids=taxonomy_ids,
    )


class TaxonomyResearcherScheduler:
    """Clone of arp.discovery.scheduler.DiscoveryScheduler's shape (see its
    docstring for the full rationale) -- config persisted to
    <taxonomy_researcher_state_dir>/schedule.json, survives restarts;
    manual trigger and scheduled firing share the exact same
    run_taxonomy_research entry point.
    """

    def __init__(
        self, settings: Settings, run_store: RunStore, taxonomy_store: TaxonomyStore,
        llm_factory: Callable[[], LLMClient], search_client: WebSearchClient,
    ) -> None:
        self.settings = settings
        self.run_store = run_store
        self.taxonomy_store = taxonomy_store
        self._llm_factory = llm_factory  # zero-arg callable -- deferred so a missing API key only errors when a run actually fires
        self._search_client = search_client
        self._scheduler = AsyncIOScheduler()
        self._config_path: Path = settings.taxonomy_researcher_state_dir / "schedule.json"

    def load_config(self) -> TaxonomyResearcherScheduleConfig:
        if self._config_path.exists():
            try:
                return TaxonomyResearcherScheduleConfig.model_validate_json(self._config_path.read_text())
            except (json.JSONDecodeError, ValueError):
                pass
        return TaxonomyResearcherScheduleConfig(
            enabled=self.settings.taxonomy_researcher_schedule_enabled,
            interval_hours=self.settings.taxonomy_researcher_schedule_interval_hours,
        )

    def save_config(self, config: TaxonomyResearcherScheduleConfig) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(config.model_dump_json(indent=2))
        self._apply(config)

    def start(self) -> None:
        self._scheduler.start()
        self._apply(self.load_config())

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def _apply(self, config: TaxonomyResearcherScheduleConfig) -> None:
        if self._scheduler.get_job(_JOB_ID):
            self._scheduler.remove_job(_JOB_ID)
        if not config.enabled:
            return
        self._scheduler.add_job(
            self._run_scheduled, "interval", hours=config.interval_hours, id=_JOB_ID,
            next_run_time=datetime.now(UTC) + timedelta(seconds=5),
        )

    async def _run_scheduled(self) -> None:
        config = self.load_config()
        if not config.enabled:
            return
        try:
            run_id = await run_taxonomy_research(
                llm=self._llm_factory(), search_client=self._search_client, settings=self.settings,
                taxonomy_store=self.taxonomy_store, run_store=self.run_store,
                taxonomy_ids=config.taxonomy_ids, triggered_by="schedule",
            )
            config.last_run_id = run_id
            self._config_path.write_text(config.model_dump_json(indent=2))
        except Exception:  # noqa: BLE001 - a scheduled run failing must not kill the scheduler
            logger.exception("Scheduled taxonomy research run failed")
