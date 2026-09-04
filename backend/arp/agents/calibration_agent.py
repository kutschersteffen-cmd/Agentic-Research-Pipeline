from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from arp.config import Settings
from arp.ingestion.registry import DocumentSourceRegistry
from arp.orchestration.job_manager import JobManager
from arp.research.pipeline import load_theme_run_matches
from arp.schemas.calibration import CalibrationScheduleConfig, DriftFlag
from arp.schemas.common import CompanyRef, JobStatus
from arp.schemas.thematic import CompanyMatch
from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)

_JOB_ID = "calibration-agent-schedule"
_COMPLETED_STATUSES = (JobStatus.COMPLETED, JobStatus.PARTIALLY_COMPLETED)


async def check_company_staleness(
    company: CompanyRef, matches: list[CompanyMatch], registry: DocumentSourceRegistry, source_run_id: str
) -> list[DriftFlag]:
    """Pure timestamp comparison, no LLM call: if any of this company's
    currently-fetchable documents were fetched after a given match's
    generated_at, that verdict may be stale -- flagged for a human to
    decide whether re-running classification is warranted. Not a claim
    that the verdict IS wrong, just that newer evidence exists.

    Uses SourceDocument.fetched_at (ingestion time) since that's the only
    timestamp this system actually records on a document -- not
    necessarily the filing's true publication date, so this flags "we
    fetched something new," not "something new was published." Stated
    here plainly rather than implied.
    """
    documents = await registry.fetch_all(company)
    if not documents:
        return []
    newest_document_at = max(d.fetched_at for d in documents)
    return [
        DriftFlag(
            source_run_id=source_run_id, company_id=m.company_id, activity_id=m.activity_id,
            old_verdict=m.verdict, old_confidence=m.confidence, old_generated_at=m.generated_at,
            newest_document_at=newest_document_at,
            reason="A disclosure was fetched after this verdict was generated -- re-running classification is recommended.",
        )
        for m in matches
        if newest_document_at > m.generated_at
    ]


def _group_by_company(matches: list[CompanyMatch]) -> dict[str, list[CompanyMatch]]:
    grouped: dict[str, list[CompanyMatch]] = defaultdict(list)
    for m in matches:
        grouped[m.company_id].append(m)
    return grouped


def create_calibration_run(run_store: RunStore, triggered_by: str) -> str:
    """Creates the run manifest synchronously (fast, file-only) so an API
    caller gets a run_id back immediately -- execute_calibration_run does
    the actual (potentially slow) scanning and can be scheduled in the
    background. Mirrors discovery/pipeline.py's create/execute split.
    """
    theme_runs = [m for m in run_store.list_runs("theme") if m.status in _COMPLETED_STATUSES]
    job_manager = JobManager(run_store)
    manifest = job_manager.create_run("calibration", {"triggered_by": triggered_by}, len(theme_runs))
    return manifest.run_id


async def execute_calibration_run(run_id: str, *, registry: DocumentSourceRegistry, run_store: RunStore) -> str:
    """Scans every completed theme run (scoped to theme runs only for v1,
    matching load_theme_run_matches's existing scope), flags any
    (company, activity) verdict for which newer disclosures have since
    been fetched, and logs every DriftFlag against an already-created run
    (see create_calibration_run). Findings themselves are the human-facing
    review surface (GET /api/calibration/runs/{run_id}/results) -- no
    review_queue.py integration, since that queue is scoped per-source-run
    and would just duplicate what this run's own results already provide.
    """
    theme_runs = [m for m in run_store.list_runs("theme") if m.status in _COMPLETED_STATUSES]
    job_manager = JobManager(run_store)

    for source_manifest in theme_runs:
        try:
            matches = load_theme_run_matches(run_store, source_manifest.run_id) or []
            by_company = _group_by_company(matches)
            flag_count = 0
            for company_id, company_matches in by_company.items():
                company = CompanyRef(company_id=company_id, name=company_matches[0].name, ticker=company_matches[0].ticker)
                flags = await check_company_staleness(company, company_matches, registry, source_manifest.run_id)
                for flag in flags:
                    run_store.append_jsonl(run_store.results_path(run_id), flag.model_dump(mode="json"))
                flag_count += len(flags)
            job_manager.record_progress(run_id, completed_delta=1, review_delta=flag_count)
        except Exception:  # noqa: BLE001 - one source run failing must not abort the whole pass
            logger.exception("Calibration check failed for source run_id=%s", source_manifest.run_id)
            job_manager.record_progress(run_id, failed_delta=1)

    job_manager.finish_run(run_id)
    return run_id


async def run_calibration_pass(
    *, registry: DocumentSourceRegistry, run_store: RunStore, triggered_by: str = "manual"
) -> str:
    """Convenience wrapper (create + execute in one call) for the CLI and
    the scheduler, where blocking until completion is expected."""
    run_id = create_calibration_run(run_store, triggered_by)
    return await execute_calibration_run(run_id, registry=registry, run_store=run_store)


class CalibrationAgentScheduler:
    """Clone of arp.discovery.scheduler.DiscoveryScheduler's shape -- see
    its docstring for the full rationale. Config persisted to
    <calibration_agent_state_dir>/schedule.json.
    """

    def __init__(self, settings: Settings, run_store: RunStore, registry: DocumentSourceRegistry) -> None:
        self.settings = settings
        self.run_store = run_store
        self.registry = registry
        self._scheduler = AsyncIOScheduler()
        self._config_path: Path = settings.calibration_agent_state_dir / "schedule.json"

    def load_config(self) -> CalibrationScheduleConfig:
        if self._config_path.exists():
            try:
                return CalibrationScheduleConfig.model_validate_json(self._config_path.read_text())
            except (json.JSONDecodeError, ValueError):
                pass
        return CalibrationScheduleConfig(
            enabled=self.settings.calibration_agent_schedule_enabled,
            interval_hours=self.settings.calibration_agent_schedule_interval_hours,
        )

    def save_config(self, config: CalibrationScheduleConfig) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(config.model_dump_json(indent=2))
        self._apply(config)

    def start(self) -> None:
        self._scheduler.start()
        self._apply(self.load_config())

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def _apply(self, config: CalibrationScheduleConfig) -> None:
        if self._scheduler.get_job(_JOB_ID):
            self._scheduler.remove_job(_JOB_ID)
        if not config.enabled:
            return
        self._scheduler.add_job(
            self._run_scheduled, "interval", hours=config.interval_hours, id=_JOB_ID,
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=5),
        )

    async def _run_scheduled(self) -> None:
        config = self.load_config()
        if not config.enabled:
            return
        try:
            run_id = await run_calibration_pass(registry=self.registry, run_store=self.run_store, triggered_by="schedule")
            config.last_run_id = run_id
            self._config_path.write_text(config.model_dump_json(indent=2))
        except Exception:  # noqa: BLE001 - a scheduled run failing must not kill the scheduler
            logger.exception("Scheduled calibration run failed")
