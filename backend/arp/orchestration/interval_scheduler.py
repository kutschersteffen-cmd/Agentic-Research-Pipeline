from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pydantic import BaseModel

from arp.storage.atomic_io import atomic_write_text

logger = logging.getLogger(__name__)


class IntervalScheduler:
    """Owns one automatic (scheduled) run and exposes the same entry point
    manual triggers use, so "run automatically" and "run now" never diverge
    in behavior.

    Schedule configuration is persisted to `<state_dir>/schedule.json`,
    consistent with the rest of the system's file-based, no-DB storage, and
    survives process restarts. Subclasses supply the config model, job id,
    defaults and the run itself.
    """

    config_cls: ClassVar[type[BaseModel]]
    job_id: ClassVar[str]

    def __init__(self, state_dir: Path) -> None:
        self._scheduler = AsyncIOScheduler()
        self._config_path: Path = state_dir / "schedule.json"

    def _default_config(self) -> Any:
        raise NotImplementedError

    def _ready(self, config: Any) -> bool:
        return config.enabled

    async def _run(self, config: Any) -> None:
        """Run once and record the outcome on `config` (e.g. last_run_id);
        the caller persists it."""
        raise NotImplementedError

    def load_config(self) -> Any:
        if self._config_path.exists():
            try:
                return self.config_cls.model_validate_json(self._config_path.read_text())
            except (json.JSONDecodeError, ValueError):
                pass
        return self._default_config()

    def save_config(self, config: BaseModel) -> None:
        self._write(config)
        self._apply(config)

    def start(self) -> None:
        self._scheduler.start()
        self._apply(self.load_config())

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def _write(self, config: BaseModel) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self._config_path, config.model_dump_json(indent=2))

    def _apply(self, config: Any) -> None:
        if self._scheduler.get_job(self.job_id):
            self._scheduler.remove_job(self.job_id)
        if not self._ready(config):
            return
        self._scheduler.add_job(
            self._run_scheduled,
            "interval",
            hours=config.interval_hours,
            id=self.job_id,
            next_run_time=datetime.now(UTC) + timedelta(seconds=5),
        )

    async def _run_scheduled(self) -> None:
        config = self.load_config()
        if not self._ready(config):
            return
        try:
            await self._run(config)
            self._write(config)
        except Exception:  # noqa: BLE001 - a scheduled run failing must not kill the scheduler
            logger.exception("Scheduled %s run failed", self.job_id)
