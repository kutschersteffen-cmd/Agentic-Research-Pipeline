from __future__ import annotations

from datetime import UTC, datetime

from arp.config import Settings
from arp.orchestration.interval_scheduler import IntervalScheduler
from arp.portfolio.monitoring.evaluator import evaluate_news_triggers, evaluate_threshold_rules
from arp.schemas.portfolio_monitoring import PortfolioMonitoringScheduleConfig
from arp.storage.portfolio_store import PortfolioStore


class PortfolioMonitoringScheduler(IntervalScheduler):
    """Scheduled threshold + news evaluation; config in
    `<portfolio_monitoring_state_dir>/schedule.json`."""

    config_cls = PortfolioMonitoringScheduleConfig
    job_id = "portfolio-monitoring-schedule"

    def __init__(self, settings: Settings, store: PortfolioStore) -> None:
        super().__init__(settings.portfolio_monitoring_state_dir)
        self.settings = settings
        self.store = store

    def _default_config(self) -> PortfolioMonitoringScheduleConfig:
        return PortfolioMonitoringScheduleConfig(
            enabled=self.settings.portfolio_monitoring_schedule_enabled,
            interval_hours=self.settings.portfolio_monitoring_schedule_interval_hours,
            news_min_severity=self.settings.portfolio_monitoring_news_min_severity,
        )

    async def _run(self, config: PortfolioMonitoringScheduleConfig) -> None:
        evaluate_threshold_rules(self.store)
        evaluate_news_triggers(self.store, min_severity=config.news_min_severity)
        config.last_run_at = datetime.now(UTC).isoformat()
