from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from arp.config import Settings
from arp.discovery.pipeline import run_discovery
from arp.schemas.discovery import DiscoveryScheduleConfig
from arp.storage.run_store import RunStore
from arp.universe import load_company_universe

logger = logging.getLogger(__name__)

_JOB_ID = "discovery-schedule"


class DiscoveryScheduler:
    """Owns the automatic (scheduled) discovery run and exposes the same
    entry point manual triggers use, so "run automatically" and "run now"
    never diverge in behavior.

    Schedule configuration is persisted to a small JSON file under
    `discovery_state_dir/schedule.json`, consistent with the rest of the
    system's file-based, no-DB storage, and survives process restarts.
    """

    def __init__(self, settings: Settings, run_store: RunStore) -> None:
        self.settings = settings
        self.run_store = run_store
        self._scheduler = AsyncIOScheduler()
        self._config_path: Path = settings.discovery_state_dir / "schedule.json"

    def load_config(self) -> DiscoveryScheduleConfig:
        if self._config_path.exists():
            try:
                return DiscoveryScheduleConfig.model_validate_json(self._config_path.read_text())
            except (json.JSONDecodeError, ValueError):
                pass
        return DiscoveryScheduleConfig(
            enabled=self.settings.discovery_schedule_enabled,
            interval_hours=self.settings.discovery_schedule_interval_hours,
            universe_path=str(self.settings.discovery_schedule_universe_path)
            if self.settings.discovery_schedule_universe_path
            else None,
        )

    def save_config(self, config: DiscoveryScheduleConfig) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(config.model_dump_json(indent=2))
        self._apply(config)

    def start(self) -> None:
        self._scheduler.start()
        self._apply(self.load_config())

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def _apply(self, config: DiscoveryScheduleConfig) -> None:
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
            run_id = await run_discovery(
                companies,
                settings=self.settings,
                run_store=self.run_store,
                doc_types=config.doc_types or None,
                triggered_by="schedule",
            )
            config.last_run_id = run_id
            self._config_path.write_text(config.model_dump_json(indent=2))
        except Exception:  # noqa: BLE001 - a scheduled run failing must not kill the scheduler
            logger.exception("Scheduled discovery run failed")
