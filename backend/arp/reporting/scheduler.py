from __future__ import annotations

import logging
from collections.abc import Callable

from pydantic import BaseModel, Field

from arp.config import Settings
from arp.llm.base import LLMClient
from arp.orchestration.interval_scheduler import IntervalScheduler
from arp.reporting.service import ReportingService
from arp.schemas.reporting import ReportStatus
from arp.storage.reporting_store import ReportingStore

logger = logging.getLogger(__name__)


class ReportScheduleConfig(BaseModel):
    enabled: bool = False
    interval_hours: int = 720
    report_ids: list[str] = Field(default_factory=list)


class ReportScheduler(IntervalScheduler):
    """Periodic house-deck re-runs: each listed report is re-run on fresh pipeline data as a new report."""

    config_cls = ReportScheduleConfig
    job_id = "report_reruns"

    def __init__(self, settings: Settings, llm_factory: Callable[[], LLMClient]) -> None:
        super().__init__(settings.reports_dir / "_schedule")
        self.service = ReportingService(ReportingStore(settings.reports_dir, settings.report_templates_dir), settings)
        self._llm_factory = llm_factory  # deferred so a missing API key only errors when a run fires

    def _default_config(self) -> ReportScheduleConfig:
        return ReportScheduleConfig()

    async def _run(self, config: ReportScheduleConfig) -> None:
        llm = self._llm_factory()
        for report_id in config.report_ids:
            try:
                waiting = next((m for m in self.service.lineage(report_id) if m.rerun_of and m.status == ReportStatus.STORYLINE_READY), None)
                if waiting is None:
                    waiting = await self.service.rerun(report_id, llm)
                if waiting.status == ReportStatus.STORYLINE_READY:  # warned every tick until a person acts
                    logger.warning("Scheduled re-run of report %s is waiting for storyline approval as report %s", report_id, waiting.report_id)
            except Exception:  # noqa: BLE001 - one broken report must not stop the others
                logger.exception("Scheduled re-run of report %s failed", report_id)
