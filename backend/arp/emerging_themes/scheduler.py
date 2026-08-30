from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from arp.config import Settings
from arp.emerging_themes.ingestion.base import MentionSource
from arp.emerging_themes.ingestion.edgar_fts import EdgarFullTextSearchSource
from arp.emerging_themes.ingestion.gdelt import GdeltSource
from arp.emerging_themes.ingestion.regulatory_rss import RegulatoryRssSource
from arp.emerging_themes.pipeline import run_emerging_themes
from arp.llm.base import LLMClient
from arp.schemas.emerging_themes import EmergingThemesScheduleConfig
from arp.storage.run_store import RunStore
from arp.storage.topic_store import TopicStateStore
from arp.universe import load_company_universe

logger = logging.getLogger(__name__)

_JOB_ID = "emerging-themes-schedule"


def default_sources(settings: Settings) -> list[MentionSource]:
    """Phase 1's three no-API-key sources -- see docs for why UK NSM/EU
    ESAP connectors aren't included here yet (Phase 2)."""
    return [
        EdgarFullTextSearchSource(settings.edgar_user_agent),
        GdeltSource(max_records=settings.emerging_themes_gdelt_max_records),
        RegulatoryRssSource(),
    ]


class EmergingThemesScheduler:
    """Clone of `discovery/scheduler.py::DiscoveryScheduler`'s shape (see
    its docstring for the full rationale) -- config persisted to
    `<emerging_themes_state_dir>/schedule.json`, survives restarts; manual
    trigger and scheduled firing share the exact same
    `run_emerging_themes` entry point.
    """

    def __init__(
        self, settings: Settings, run_store: RunStore, topic_store: TopicStateStore, llm_factory: Callable[[], LLMClient]
    ) -> None:
        self.settings = settings
        self.run_store = run_store
        self.topic_store = topic_store
        self._llm_factory = llm_factory  # zero-arg callable -- deferred so a missing API key only errors when a run actually fires
        self._scheduler = AsyncIOScheduler()
        self._config_path: Path = settings.emerging_themes_state_dir / "schedule.json"

    def load_config(self) -> EmergingThemesScheduleConfig:
        if self._config_path.exists():
            try:
                return EmergingThemesScheduleConfig.model_validate_json(self._config_path.read_text())
            except (json.JSONDecodeError, ValueError):
                pass
        return EmergingThemesScheduleConfig(
            enabled=self.settings.emerging_themes_schedule_enabled,
            interval_hours=self.settings.emerging_themes_schedule_interval_hours,
            universe_path=str(self.settings.emerging_themes_schedule_universe_path)
            if self.settings.emerging_themes_schedule_universe_path
            else None,
        )

    def save_config(self, config: EmergingThemesScheduleConfig) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(config.model_dump_json(indent=2))
        self._apply(config)

    def start(self) -> None:
        self._scheduler.start()
        self._apply(self.load_config())

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def _apply(self, config: EmergingThemesScheduleConfig) -> None:
        if self._scheduler.get_job(_JOB_ID):
            self._scheduler.remove_job(_JOB_ID)
        if not config.enabled or not config.universe_path:
            return
        self._scheduler.add_job(
            self._run_scheduled,
            "interval",
            hours=config.interval_hours,
            id=_JOB_ID,
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=5),
        )

    async def _run_scheduled(self) -> None:
        config = self.load_config()
        if not config.enabled or not config.universe_path:
            return
        try:
            companies = load_company_universe(config.universe_path)
            run_id = await run_emerging_themes(
                companies,
                llm=self._llm_factory(),
                sources=default_sources(self.settings),
                settings=self.settings,
                run_store=self.run_store,
                topic_store=self.topic_store,
                triggered_by="schedule",
            )
            config.last_run_id = run_id
            self._config_path.write_text(config.model_dump_json(indent=2))
        except Exception:  # noqa: BLE001 - a scheduled run failing must not kill the scheduler
            logger.exception("Scheduled emerging themes run failed")
