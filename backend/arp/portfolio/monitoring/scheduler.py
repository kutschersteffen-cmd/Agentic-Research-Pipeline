from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from arp.config import Settings
from arp.portfolio.monitoring.evaluator import evaluate_news_triggers, evaluate_threshold_rules
from arp.schemas.portfolio_monitoring import PortfolioMonitoringScheduleConfig
from arp.storage.portfolio_store import PortfolioStore

logger = logging.getLogger(__name__)

_JOB_ID = "portfolio-monitoring-schedule"


class PortfolioMonitoringScheduler:
    """Clone of arp.agents.calibration_agent.CalibrationAgentScheduler's
    shape (itself a clone of discovery/scheduler.py::DiscoveryScheduler) --
    see either docstring for the full rationale. Config persisted to
    <portfolio_monitoring_state_dir>/schedule.json.
    """

    def __init__(self, settings: Settings, store: PortfolioStore) -> None:
        self.settings = settings
        self.store = store
        self._scheduler = AsyncIOScheduler()
        self._config_path: Path = settings.portfolio_monitoring_state_dir / "schedule.json"

    def load_config(self) -> PortfolioMonitoringScheduleConfig:
        if self._config_path.exists():
            try:
                return PortfolioMonitoringScheduleConfig.model_validate_json(self._config_path.read_text())
            except (json.JSONDecodeError, ValueError):
                pass
        return PortfolioMonitoringScheduleConfig(
            enabled=self.settings.portfolio_monitoring_schedule_enabled,
            interval_hours=self.settings.portfolio_monitoring_schedule_interval_hours,
            news_min_severity=self.settings.portfolio_monitoring_news_min_severity,
        )

    def save_config(self, config: PortfolioMonitoringScheduleConfig) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(config.model_dump_json(indent=2))
        self._apply(config)

    def start(self) -> None:
        self._scheduler.start()
        self._apply(self.load_config())

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def _apply(self, config: PortfolioMonitoringScheduleConfig) -> None:
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
            evaluate_threshold_rules(self.store)
            evaluate_news_triggers(self.store, min_severity=config.news_min_severity)
            config.last_run_at = datetime.now(UTC).isoformat()
            self._config_path.write_text(config.model_dump_json(indent=2))
        except Exception:  # noqa: BLE001 - a scheduled run failing must not kill the scheduler
            logger.exception("Scheduled portfolio monitoring evaluation failed")
