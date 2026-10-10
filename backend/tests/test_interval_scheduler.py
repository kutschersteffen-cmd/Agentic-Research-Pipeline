import asyncio

import pytest

from arp.agents.calibration_agent import CalibrationAgentScheduler
from arp.config import Settings
from arp.schemas.calibration import CalibrationScheduleConfig


class _Scheduler(CalibrationAgentScheduler):
    def __init__(self, settings: Settings, fail: bool = False) -> None:
        super().__init__(settings, run_store=None, registry=None)
        self.fail = fail

    async def _run(self, config: CalibrationScheduleConfig) -> None:
        if self.fail:
            raise RuntimeError("boom")
        config.last_run_id = "run-1"


def _settings(tmp_path) -> Settings:
    return Settings(calibration_agent_state_dir=tmp_path, calibration_agent_schedule_enabled=False)


async def test_defaults_come_from_settings_until_a_config_is_saved(tmp_path):
    s = _Scheduler(_settings(tmp_path))
    assert s.load_config() == CalibrationScheduleConfig(enabled=False, interval_hours=24.0)
    s.start()
    assert s._task is None

    s.save_config(CalibrationScheduleConfig(enabled=True, interval_hours=6))
    await asyncio.sleep(0)
    assert s.load_config().interval_hours == 6
    assert s._task is not None and s._interval(s.load_config()) == 6 * 3600

    s.save_config(CalibrationScheduleConfig(enabled=False))
    await asyncio.sleep(0)
    assert s._task is None
    s.shutdown()


async def test_tick_runs_immediately_then_every_interval(tmp_path, monkeypatch):
    s = _Scheduler(_settings(tmp_path))
    s._write(CalibrationScheduleConfig(enabled=True))
    runs, sleeps = [], []
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) > 2:
            raise asyncio.CancelledError
        await real_sleep(0)

    async def run(config):
        runs.append(1)
        config.last_run_id = "r"

    s._run = run
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await s._tick(3600)
    assert sleeps == [5, 3600, 3600] and len(runs) == 2


def test_corrupt_config_falls_back_to_defaults(tmp_path):
    (tmp_path / "schedule.json").write_text("{not json")
    assert _Scheduler(_settings(tmp_path)).load_config().enabled is False


async def test_scheduled_run_persists_outcome_and_survives_failure(tmp_path):
    s = _Scheduler(_settings(tmp_path))
    s._write(CalibrationScheduleConfig(enabled=True))
    await s._run_scheduled()
    assert s.load_config().last_run_id == "run-1"

    failing = _Scheduler(_settings(tmp_path), fail=True)
    await failing._run_scheduled()  # must not raise
    assert failing.load_config().last_run_id == "run-1"


async def test_disabled_schedule_does_not_run(tmp_path):
    s = _Scheduler(_settings(tmp_path))
    s._write(CalibrationScheduleConfig(enabled=False))
    await s._run_scheduled()
    assert s.load_config().last_run_id is None
