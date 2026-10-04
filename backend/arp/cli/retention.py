from __future__ import annotations

import typer

from arp.config import get_settings
from arp.retention import cleanup

retention_app = typer.Typer(help="Retention: delete only what is past its retention period.")


@retention_app.command("cleanup")
def cleanup_cmd(apply: bool = typer.Option(False, "--apply", help="Delete. Without it this is a dry run.")) -> None:
    """Report (or with --apply delete) run files and stored originals past their retention period."""
    settings = get_settings()
    held_runs: set[str] = set()
    held_keys: set[str] = set()
    if settings.postgres_dsn:
        from arp.publish.facts import PublishStore

        held_runs, held_keys = PublishStore(settings.postgres_dsn).referenced()
    report = cleanup(settings, apply=apply, held_runs=held_runs, held_keys=held_keys)
    verb = "deleted" if apply else "would delete"
    for p in report.deleted:
        typer.echo(f"{verb}: {p}")
    for h in report.held:
        typer.echo(f"held: {h}")
    typer.echo(f"{verb} {len(report.deleted)}, held {len(report.held)}, kept {report.kept}")
