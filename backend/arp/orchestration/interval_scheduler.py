from __future__ import annotations

import json
import logging
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar, Literal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pydantic import BaseModel

from arp.storage.atomic_io import atomic_write_text

logger = logging.getLogger(__name__)


def calendar_due(
    today: date, *, dates: list[str], rule: Literal["month_end", "quarter_end"] | None, last_fire: str | None
) -> str | None:
    """ISO date to fire for, or None. A listed date fires on the day or the next tick
    (once: only dates after `last_fire` count); a rule fires on its day."""
    cands = [d for d in dates if d <= today.isoformat()]
    if rule and today.day == monthrange(today.year, today.month)[1] and (rule == "month_end" or today.month % 3 == 0):
        cands.append(today.isoformat())
    cands = [d for d in cands if last_fire is None or d > last_fire]
    return max(cands) if cands else None


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

    @staticmethod
    def _calendar(config: Any) -> bool:
        return bool(getattr(config, "calendar_dates", None) or getattr(config, "calendar_rule", None))

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
            hours=24 if self._calendar(config) else config.interval_hours,
            id=self.job_id,
            next_run_time=datetime.now(UTC) + timedelta(seconds=5),
        )

    async def _run_scheduled(self) -> None:
        config = self.load_config()
        if not self._ready(config):
            return
        due = None
        if self._calendar(config):
            due = calendar_due(
                datetime.now(UTC).date(), dates=config.calendar_dates, rule=config.calendar_rule,
                last_fire=config.last_calendar_fire,
            )
            if due is None:
                return
        try:
            await self._run(config)
            if due:
                config.last_calendar_fire = due
            self._write(config)
        except Exception:  # noqa: BLE001 - a scheduled run failing must not kill the scheduler
            logger.exception("Scheduled %s run failed", self.job_id)
