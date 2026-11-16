from __future__ import annotations

from arp.config import Settings
from arp.discovery.pipeline import run_discovery
from arp.orchestration.interval_scheduler import IntervalScheduler
from arp.schemas.discovery import DiscoveryScheduleConfig
from arp.storage.run_store import RunStore
from arp.universe import load_company_universe


class DiscoveryScheduler(IntervalScheduler):
    """Scheduled discovery run; config in `discovery_state_dir/schedule.json`."""

    config_cls = DiscoveryScheduleConfig
    job_id = "discovery-schedule"

    def __init__(self, settings: Settings, run_store: RunStore) -> None:
        super().__init__(settings.discovery_state_dir)
        self.settings = settings
        self.run_store = run_store

    def _default_config(self) -> DiscoveryScheduleConfig:
        s = self.settings
        return DiscoveryScheduleConfig(
            enabled=s.discovery_schedule_enabled,
            interval_hours=s.discovery_schedule_interval_hours,
            universe_path=str(s.discovery_schedule_universe_path) if s.discovery_schedule_universe_path else None,
        )

    def _ready(self, config: DiscoveryScheduleConfig) -> bool:
        return config.enabled and bool(config.universe_path)

    async def _run(self, config: DiscoveryScheduleConfig) -> None:
        config.last_run_id = await run_discovery(
            load_company_universe(config.universe_path),
            settings=self.settings,
            run_store=self.run_store,
            doc_types=config.doc_types or None,
            triggered_by="schedule",
        )
