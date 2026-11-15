from __future__ import annotations

import asyncio
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


@stewardship_app.command("watch-golden")
def watch_golden_cmd(
    kind: Literal["check", "find"] = typer.Option(..., "--kind"),
    cases: Path = typer.Option(..., "--cases", exists=True, dir_okay=False, help="Labelled cases (JSON)."),
    documents_dir: Path = typer.Option(..., "--documents-dir", help="Directory with the check cases' documents."),
    min_precision: float = typer.Option(..., "--min-precision", help="Exit 1 below this precision."),
    min_coverage: float = typer.Option(..., "--min-coverage", help="Exit 1 below this coverage."),
) -> None:
    """Run the real model on the watch-check or find-commitments golden set; print precision and coverage."""
    from arp.llm.factory import build_llm_client
    from arp.stewardship.watch_golden import load_cases, score_check, score_find

    settings = get_settings()
    llm, fuzzy, misses = build_llm_client(settings), settings.grounding_fuzzy_threshold, []
    labelled = load_cases(cases, kind)
    run = score_check(labelled, documents_dir, llm, fuzzy, misses) if kind == "check" else score_find(labelled, llm, fuzzy, misses)
    precision, coverage = asyncio.run(run)
    for miss in misses:
        typer.echo(miss, err=True)
    typer.echo(f"precision {precision:.2f}, coverage {coverage:.2f}")
    if precision < min_precision or coverage < min_coverage:
        raise typer.Exit(1)
