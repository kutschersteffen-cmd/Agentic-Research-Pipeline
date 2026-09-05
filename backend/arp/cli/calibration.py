from __future__ import annotations

import asyncio

import typer

from arp.agents.calibration_agent import CalibrationAgentScheduler, run_calibration_pass
from arp.cli._shared import _registry, _run_store
from arp.config import get_settings
from arp.schemas.calibration import CalibrationScheduleConfig

calibration_app = typer.Typer(help="Standing agent: flags theme-run verdicts for which newer company disclosures have since arrived -- never auto-re-runs classification.")


@calibration_app.command("run")
def calibration_run() -> None:
    """Flags theme-run verdicts for which newer company disclosures have
    since arrived -- never re-runs classification or changes a prior
    verdict itself. Uses the exact same pipeline the automatic schedule
    uses."""
    run_store = _run_store()
    run_id = asyncio.run(run_calibration_pass(registry=_registry(), run_store=run_store, triggered_by="manual"))
    rows = run_store.read_jsonl(run_store.results_path(run_id))
    typer.echo(f"Run complete: {run_id} -- {len(rows)} drift flag(s) logged.")



@calibration_app.command("schedule")
def calibration_schedule(
    interval_hours: float = typer.Option(24.0),
    enable: bool = typer.Option(True, help="Pass --no-enable to disable."),
) -> None:
    """Configures the automatic recurring calibration pass. Takes effect
    the next time the API server process starts (it owns the scheduler);
    this command just persists the config file it reads."""
    settings = get_settings()
    scheduler = CalibrationAgentScheduler(settings, _run_store(), _registry())
    config = CalibrationScheduleConfig(enabled=enable, interval_hours=interval_hours)
    scheduler.save_config(config)
    typer.echo(f"Schedule saved: enabled={enable}, every {interval_hours}h")
