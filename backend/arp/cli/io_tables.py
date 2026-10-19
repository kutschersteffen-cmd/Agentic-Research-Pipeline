from __future__ import annotations

import csv
import zipfile
from pathlib import Path

import typer
from pydantic import ValidationError

from arp.config import Settings
from arp.research.indirect_exposure.factory import active_io_source
from arp.research.indirect_exposure.icio_loader import read_industries
from arp.research.indirect_exposure.io_import import import_exiobase, import_icio

io_app = typer.Typer(help="Import OECD ICIO / EXIOBASE input-output tables and show which one is active.")


def _run_import(fn, *args) -> None:
    try:
        lines = fn(*args)
    except (ValueError, OSError, csv.Error, zipfile.BadZipFile, StopIteration) as exc:
        typer.echo(" ".join(str(exc).split()) or f"{type(exc).__name__}: unexpected end of file", err=True)
        raise typer.Exit(1) from exc
    for line in lines:
        typer.echo(line)


@io_app.command("import-icio")
def io_import_icio(
    csv_file: Path = typer.Argument(..., help="One OECD ICIO 2025 year file, e.g. 2022_SML.csv."),
    out: Path = typer.Option(..., "--out", help="Output directory (created if missing)."),
    label: str = typer.Option(None, "--label", help="Edition label; defaults to icio-<file stem>."),
) -> None:
    """Writes industries.csv, icio_matrix.csv, final_demand.csv and the regional files, then prints the settings to use them."""
    _run_import(import_icio, csv_file, out, label)


@io_app.command("import-exiobase")
def io_import_exiobase(
    zip_file: Path = typer.Argument(..., help="One EXIOBASE 3 ixi archive, e.g. IOT_2022_ixi.zip."),
    out: Path = typer.Option(..., "--out", help="Output directory (created if missing)."),
    label: str = typer.Option(None, "--label", help="Edition label; defaults to exiobase-<archive stem>."),
    split_electricity: bool = typer.Option(
        False, "--split-electricity", help="Split D into generation (fossil/nuclear/renewables), grid and gas."
    ),
) -> None:
    """Writes industries.csv, exiobase_flows.csv, final_demand.csv, ghg.csv and the regional files, then prints the settings to use them."""
    _run_import(import_exiobase, zip_file, out, label, split_electricity)


@io_app.command("status")
def io_status() -> None:
    """Which input-output table backs runs, and which optional parts it has."""
    try:
        settings = Settings()
        source = active_io_source(settings)
    except (ValidationError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"source: {source or 'none'}")
    if source is None:
        return
    if source == "icio":
        label, industries = settings.icio_edition_label, settings.icio_industries_path
    else:
        label, industries = settings.exiobase_edition_label, settings.exiobase_industries_path
    folder = industries.parent
    regional = folder / "regional_output.csv"
    regions = "no"
    try:
        n_industries = len(read_industries(industries)[0])
        if regional.exists():
            with regional.open() as f:
                regions = str(len({line.split(",", 1)[0] for line in list(f)[1:] if line.strip()}))
    except (OSError, ValueError, KeyError) as exc:
        typer.echo(f"cannot read {industries}: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"edition: {label}")
    typer.echo(f"industries: {n_industries}")
    typer.echo(f"final demand: {'yes' if (folder / 'final_demand.csv').exists() else 'no'}")
    typer.echo(f"emissions: {'yes' if (folder / 'ghg.csv').exists() else 'no'}")
    typer.echo(f"regions: {regions}")
