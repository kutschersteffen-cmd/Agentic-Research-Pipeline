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


def test_defaults_come_from_settings_until_a_config_is_saved(tmp_path):
    s = _Scheduler(_settings(tmp_path))
    assert s.load_config() == CalibrationScheduleConfig(enabled=False, interval_hours=24.0)

    s.save_config(CalibrationScheduleConfig(enabled=True, interval_hours=6))
    assert s.load_config().interval_hours == 6
    assert s._scheduler.get_job(s.job_id) is not None

    s.save_config(CalibrationScheduleConfig(enabled=False))
    assert s._scheduler.get_job(s.job_id) is None


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
