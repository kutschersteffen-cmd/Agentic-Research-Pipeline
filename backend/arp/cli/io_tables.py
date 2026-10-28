from __future__ import annotations

import csv
import json
import os
import zipfile
from pathlib import Path

import typer
from pydantic import ValidationError

from arp.config import Settings
from arp.research.value_chain.build import build_full

io_app = typer.Typer(help="Build the full EXIOBASE input-output model and show which one is active.")

# Settings of the retired 50-industry path, reported by `arp io status` (spec 2026-10-26 Scope 9-10).
RETIRED_SETTINGS = (
    "ARP_ICIO_MATRIX_PATH", "ARP_ICIO_INDUSTRIES_PATH", "ARP_ICIO_EDITION_LABEL",
    "ARP_EXIOBASE_FLOWS_PATH", "ARP_EXIOBASE_INDUSTRIES_PATH", "ARP_EXIOBASE_EDITION_LABEL", "ARP_IO_SOURCE",
)


def _run_import(fn, *args) -> None:
    try:
        lines = fn(*args)
    except (ValueError, OSError, csv.Error, zipfile.BadZipFile, StopIteration) as exc:
        typer.echo(" ".join(str(exc).split()) or f"{type(exc).__name__}: unexpected end of file", err=True)
        raise typer.Exit(1) from exc
    for line in lines:
        typer.echo(line)


@io_app.command("build-full")
def io_build_full(
    zip_file: Path = typer.Argument(..., help="One EXIOBASE 3 ixi archive, e.g. IOT_2022_ixi.zip."),
    out: Path = typer.Option(..., "--out", help="Output directory (replaced if it exists)."),
    label: str = typer.Option(None, "--label", help="Edition label; defaults to exiobase-<archive stem>."),
) -> None:
    """Writes nodes.csv, manifest.json, the A, L, G matrices and final demand of the full EXIOBASE table, then prints the setting to use them."""
    _run_import(build_full, zip_file, out, label)


@io_app.command("status")
def io_status() -> None:
    """Which input-output build backs runs, and whether it has final demand."""
    for name in RETIRED_SETTINGS:
        if name in os.environ:
            typer.echo(f"ignored (retired): {name}", err=True)
    try:
        folder = Settings().value_chain_dir
    except ValidationError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if folder is None:
        typer.echo("source: none")
        return
    try:
        manifest = json.loads((folder / "manifest.json").read_text())
        edition, n_nodes = manifest["edition"], manifest["n_nodes"]
    except (OSError, ValueError, KeyError) as exc:
        typer.echo(f"cannot read {folder / 'manifest.json'}: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo("source: exiobase")
    typer.echo(f"edition: {edition}")
    typer.echo(f"nodes: {n_nodes}")
    typer.echo(f"final demand: {'yes' if (folder / 'Y.npy').is_file() else 'no'}")
