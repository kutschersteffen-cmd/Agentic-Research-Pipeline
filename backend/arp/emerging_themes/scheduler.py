from __future__ import annotations

from collections.abc import Callable

from arp.config import Settings
from arp.emerging_themes.ingestion.base import MentionSource
from arp.emerging_themes.ingestion.edgar_fts import EdgarFullTextSearchSource
from arp.emerging_themes.ingestion.gdelt import GdeltSource
from arp.emerging_themes.ingestion.regulatory_rss import RegulatoryRssSource
from arp.emerging_themes.pipeline import run_emerging_themes
from arp.ingestion.edgar import EdgarDocumentSource
from arp.ingestion.xbrl import XbrlFactSource
from arp.llm.base import LLMClient
from arp.orchestration.interval_scheduler import IntervalScheduler
from arp.schemas.emerging_themes import EmergingThemesScheduleConfig
from arp.storage.document_store import DocumentContentStore
from arp.storage.run_store import RunStore
from arp.storage.topic_store import TopicStateStore
from arp.universe import load_company_universe


def default_sources(settings: Settings) -> list[MentionSource]:
    """Phase 1's three no-API-key sources -- see docs for why UK NSM/EU
    ESAP connectors aren't included here yet (Phase 2)."""
    return [
        EdgarFullTextSearchSource(settings.edgar_user_agent),
        GdeltSource(max_records=settings.emerging_themes_gdelt_max_records),
        RegulatoryRssSource(),
    ]


class EmergingThemesScheduler(IntervalScheduler):
    """Scheduled emerging-themes run; config in
    `<emerging_themes_state_dir>/schedule.json`. Manual trigger and
    scheduled firing share the same `run_emerging_themes` entry point.
    """

    config_cls = EmergingThemesScheduleConfig
    job_id = "emerging-themes-schedule"

    def __init__(
        self, settings: Settings, run_store: RunStore, topic_store: TopicStateStore, llm_factory: Callable[[], LLMClient]
    ) -> None:
        super().__init__(settings.emerging_themes_state_dir)
        self.settings = settings
        self.run_store = run_store
        self.topic_store = topic_store
        self._llm_factory = llm_factory  # zero-arg callable -- deferred so a missing API key only errors when a run actually fires

    def _default_config(self) -> EmergingThemesScheduleConfig:
        s = self.settings
        return EmergingThemesScheduleConfig(
            enabled=s.emerging_themes_schedule_enabled,
            interval_hours=s.emerging_themes_schedule_interval_hours,
            universe_path=str(s.emerging_themes_schedule_universe_path) if s.emerging_themes_schedule_universe_path else None,
        )

    def _ready(self, config: EmergingThemesScheduleConfig) -> bool:
        return config.enabled and bool(config.universe_path)

    def _xbrl_source(self) -> XbrlFactSource:
        """Roadmap P3.2's structured-financials cross-check, gated by
        settings.xbrl_facts_enabled in `_run` below. Built the same way
        `api/deps.py::get_xbrl_source`/`cli.py::_xbrl_source` do -- this
        scheduler has no access to either, so it constructs its own
        EdgarDocumentSource/XbrlFactSource instance rather than sharing one."""
        edgar = EdgarDocumentSource(
            self.settings.edgar_user_agent,
            self.settings.cache_dir,
            content_store=DocumentContentStore(self.settings.document_store_dir, enabled=self.settings.document_cache_enabled),
            submissions_ttl_hours=self.settings.edgar_submissions_ttl_hours,
        )
        return XbrlFactSource(edgar, self.settings.cache_dir, ttl_hours=self.settings.xbrl_facts_ttl_hours)

    async def _run(self, config: EmergingThemesScheduleConfig) -> None:
        config.last_run_id = await run_emerging_themes(
            load_company_universe(config.universe_path),
            llm=self._llm_factory(),
            sources=default_sources(self.settings),
            settings=self.settings,
            run_store=self.run_store,
            topic_store=self.topic_store,
            triggered_by="schedule",
            xbrl_source=self._xbrl_source() if self.settings.xbrl_facts_enabled else None,
        )
