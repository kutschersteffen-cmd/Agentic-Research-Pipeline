from __future__ import annotations

import asyncio
import json
import logging
from calendar import monthrange
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel

from arp.storage.atomic_io import atomic_write_text

logger = logging.getLogger(__name__)


def calendar_due(
    today: date, *, dates: list[str], rule: Literal["month_end", "quarter_end"] | None, last_fire: str | None
) -> str | None:
    """ISO date to fire for, or None. A listed date fires on the day or the next tick
    (once: only dates after `last_fire` count); a rule fires on its day."""
    cands = [d for d in dates if d <= today.isoformat()]
    if rule:  # most recent period end <= today
        y, m = today.year, today.month
        if today.day != monthrange(y, m)[1]:
            y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        while rule == "quarter_end" and m % 3:
            y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        end = date(y, m, monthrange(y, m)[1]).isoformat()
        if last_fire is not None or end == today.isoformat():  # a new config never fires for a past period
            cands.append(end)
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
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._run_task: asyncio.Task | None = None
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
        self._loop = asyncio.get_running_loop()
        self._reschedule(self.load_config())

    def shutdown(self) -> None:
        if self._task:
            self._task.cancel()
        self._loop = self._task = None

    def _write(self, config: BaseModel) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self._config_path, config.model_dump_json(indent=2))

    def _apply(self, config: Any) -> None:
        # save_config comes from sync routes (threadpool) and the CLI (no loop,
        # not started -- the API process picks the file up on start()).
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._reschedule, config)

    def _interval(self, config: Any) -> float:
        return 24 * 3600 if self._calendar(config) else config.interval_hours * 3600

    def _reschedule(self, config: Any) -> None:
        if self._task:
            self._task.cancel()
        self._task = None
        if self._loop is not None and self._ready(config):
            self._task = self._loop.create_task(self._tick(self._interval(config)))

    async def _tick(self, seconds: float) -> None:
        await asyncio.sleep(5)
        while True:
            # Shielded and reused while still running: rescheduling mid-run
            # neither kills the run in progress nor starts an overlapping one.
            if self._run_task is None or self._run_task.done():
                self._run_task = asyncio.ensure_future(self._run_scheduled())
            await asyncio.shield(self._run_task)
            await asyncio.sleep(seconds)

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
