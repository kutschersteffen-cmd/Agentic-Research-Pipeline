from __future__ import annotations

from pathlib import Path

import typer

from arp.orchestration.plan_check import check_script
from arp.orchestration.plan_interp import PlanScriptError, StepLimitExceeded, dry_run

plan_app = typer.Typer(help="Research Orchestrator: check and dry-run plan scripts.")


@plan_app.command("check")
def check(path: Path) -> None:
    """Check a plan script against the allowed subset of Python."""
    errors = check_script(path.read_text())
    if errors:
        typer.echo("\n".join(errors))
        raise typer.Exit(1)
    typer.echo("ok")


@plan_app.command("dry-run")
def dry_run_cmd(path: Path) -> None:
    """List the steps a plan script will take, without starting any run."""
    # shortcut: takes a script file; `dry-run <plan_id>` arrives with plan storage (plan task 5).
    try:
        calls = dry_run(path.read_text())
    except (PlanScriptError, StepLimitExceeded) as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc
    for c in calls:
        dep = f"  (depends on {c['depends_on']})" if c["depends_on"] else ""
        typer.echo(f"{c['seq']} {c['kind']} {c['params']}{dep}")
