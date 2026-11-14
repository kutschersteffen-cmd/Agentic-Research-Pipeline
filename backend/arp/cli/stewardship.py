from __future__ import annotations

from pathlib import Path
from typing import Literal

import typer

from arp.config import get_settings
from arp.db.session import require_dsn
from arp.errors import ClientInputError
from arp.stewardship.intake import IntakeReport, intake_engagements, intake_votes
from arp.stewardship.intake_excel import read_workbook
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


@stewardship_app.command("intake")
def intake_cmd(file: Path = typer.Argument(..., exists=True, dir_okay=False), kind: Literal["engagements", "votes"] = typer.Option(..., "--kind")) -> None:
    """Load an engagement or vote workbook (see GET /api/stewardship/intake/template); exits 1 when any row is rejected."""
    batch, bad = read_workbook(file.read_bytes(), kind)
    if bad:  # nothing is written when the workbook itself is wrong
        report = IntakeReport(rejected=bad)
    else:
        dsn = require_dsn(get_settings())
        report = intake_votes(batch["votes"], dsn, "excel", excel_rows=True) if kind == "votes" else intake_engagements(batch, dsn, "excel", excel_rows=True)
    for r in report.rejected:
        typer.echo(f"{r.sheet} row {r.row} {r.field}: {r.reason}", err=True)
    typer.echo(f"created {report.created}, updated {report.updated}, unchanged {report.unchanged}, rejected {len(report.rejected)}")
    if report.rejected:
        raise typer.Exit(1)


@stewardship_app.command("seed-demo")
def seed_demo_cmd(
    companies: int = typer.Option(400, "--companies", help="How many MSCI World companies (heaviest first)."),
    seed: int = typer.Option(7, "--seed", help="Same seed: re-run changes nothing. Other seed: replaces the demo rows."),
) -> None:
    """Write SIMULATED VOICE engagements, objectives and activities (source mock_voice_seed); run `arp showcase load` first."""
    from arp.stewardship.seed_demo import seed_demo

    counts = seed_demo(require_dsn(get_settings()), companies, seed)
    typer.echo(", ".join(f"{k} {v}" for k, v in counts.items()))


@stewardship_app.command("load-npx")
def load_npx_cmd(directory: Path = typer.Argument(..., help="Folder with the N-PX CSVs, e.g. data/voting/npx_urth/.")) -> None:
    """Load N-PX vote CSVs into the vote ledger (source npx_urth_demo); safe to re-run, never fetches."""
    from arp.stewardship.npx_load import load_npx

    try:
        counts = load_npx(directory, require_dsn(get_settings()))
    except ClientInputError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"meetings {counts['meetings']}, items {counts['items']}, decisions {counts['decisions']} created")
