from datetime import date

from arp.config import Settings
from arp.emerging_themes.scheduler import EmergingThemesScheduler
from arp.orchestration.interval_scheduler import calendar_due
from arp.schemas.calibration import CalibrationScheduleConfig
from arp.schemas.emerging_themes import EmergingThemesScheduleConfig
from arp.schemas.portfolio_monitoring import PortfolioMonitoringScheduleConfig
from tests.test_interval_scheduler import _Scheduler, _settings


def test_trigger_fires_on_fixed_date():
    kw = {"dates": ["2026-11-15"], "rule": None}
    assert calendar_due(date(2026, 11, 14), last_fire=None, **kw) is None
    assert calendar_due(date(2026, 11, 15), last_fire=None, **kw) == "2026-11-15"
    assert calendar_due(date(2026, 11, 15), last_fire="2026-11-15", **kw) is None


def test_missed_date_fires_next_tick_once():
    kw = {"dates": ["2026-11-15"], "rule": None}
    assert calendar_due(date(2026, 11, 17), last_fire=None, **kw) == "2026-11-15"
    assert calendar_due(date(2026, 11, 18), last_fire="2026-11-15", **kw) is None


def test_month_end_and_quarter_end_rules():
    kw = {"dates": [], "last_fire": None}
    assert calendar_due(date(2026, 2, 28), rule="month_end", **kw) == "2026-02-28"
    assert calendar_due(date(2028, 2, 28), rule="month_end", **kw) is None  # leap year
    assert calendar_due(date(2026, 4, 30), rule="month_end", **kw) == "2026-04-30"
    assert calendar_due(date(2026, 4, 30), rule="quarter_end", **kw) is None
    for d in ("2026-03-31", "2026-06-30", "2026-09-30", "2026-12-31"):
        assert calendar_due(date.fromisoformat(d), rule="quarter_end", **kw) == d


async def test_interval_mode_unchanged_without_calendar(tmp_path):
    s = _Scheduler(_settings(tmp_path))
    s._write(CalibrationScheduleConfig(enabled=True))
    await s._run_scheduled()
    assert s.load_config().last_run_id == "run-1"


async def test_calendar_mode_runs_only_when_due(tmp_path):
    s = EmergingThemesScheduler(Settings(emerging_themes_state_dir=tmp_path), None, None, None)

    async def run(config):
        config.last_run_id = "r"

    s._run = run
    s._write(EmergingThemesScheduleConfig(enabled=True, universe_path="u", calendar_dates=["2000-01-01"]))
    await s._run_scheduled()
    assert s.load_config().last_calendar_fire == "2000-01-01"
    s.save_config(s.load_config().model_copy(update={"last_run_id": None}))
    await s._run_scheduled()
    assert s.load_config().last_run_id is None  # same date does not fire twice
    assert s._scheduler.get_job(s.job_id).trigger.interval.total_seconds() == 24 * 3600


def test_emerging_themes_and_monitoring_configs_accept_calendar():
    for cls in (EmergingThemesScheduleConfig, PortfolioMonitoringScheduleConfig):
        old = cls.model_validate_json('{"enabled": true}')
        assert (old.calendar_dates, old.calendar_rule, old.last_calendar_fire) == ([], None, None)
        c = cls(calendar_dates=["2026-11-15"], calendar_rule="quarter_end")
        assert cls.model_validate_json(c.model_dump_json()) == c
