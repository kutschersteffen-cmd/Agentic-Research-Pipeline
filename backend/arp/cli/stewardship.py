from __future__ import annotations

import typer

from arp.config import get_settings
from arp.db.session import require_dsn
from arp.errors import ClientInputError
from arp.stewardship.migrate import migrate_files

stewardship_app = typer.Typer(help="Stewardship data: move the file engagement records into Postgres.")


@stewardship_app.command("migrate-files")
def migrate_files_cmd(dry_run: bool = typer.Option(False, "--dry-run", help="Count what would be created; write nothing.")) -> None:
    """Copy engagements/<company>/record.json and events.jsonl into the stw_* tables (safe to re-run)."""
    settings = get_settings()
    try:
        counts = migrate_files(settings.engagements_dir, require_dsn(settings), dry_run=dry_run)
    except ClientInputError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"would create {counts['created']}" if dry_run else f"created {counts['created']}, updated {counts['updated']}, unchanged {counts['unchanged']}")
