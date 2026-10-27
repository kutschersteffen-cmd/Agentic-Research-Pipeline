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


links_app = typer.Typer(help="Link companies to value-chain nodes (docs/superpowers/specs/2026-10-27-value-chain-links-overlays-design.md).")
io_app.add_typer(links_app, name="links")


def _value_chain():
    from arp.research.value_chain.model import NotBuilt, load_value_chain

    try:
        return load_value_chain(Settings().value_chain_dir)
    except (NotBuilt, FileNotFoundError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


def _set_by() -> str:
    from arp.cli._shared import cli_principal, get_settings

    return cli_principal(get_settings()).name if os.environ.get("ARP_CLI_TOKEN", "").strip() else "cli"


@links_app.command("import")
def links_import(csv_file: Path = typer.Argument(..., exists=True, dir_okay=False, help="Header company_id,icio_code,share.")) -> None:
    """Saves one revenue split per company from the CSV rows; prints one line per rejected company."""
    from arp.cli._shared import _portfolio_store
    from arp.research.value_chain import links

    vc, store = _value_chain(), _portfolio_store()
    with csv_file.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ["company_id", "icio_code", "share"]:
            typer.echo("header must be company_id,icio_code,share", err=True)
            raise typer.Exit(1)
        splits: dict[str, list[dict]] = {}
        for row in reader:
            try:
                share: float | str = float(row["share"])
            except (TypeError, ValueError):
                share = row["share"]
            splits.setdefault(row["company_id"], []).append({"icio_code": row["icio_code"], "share": share})
    set_by, rejected = _set_by(), []
    for company_id, parts in splits.items():
        try:
            if store.get_company(company_id) is None:
                raise links.LinkError(f"unknown company '{company_id}'")
            clean = links.validate_rule(vc, "split", parts, company=True)
        except links.LinkError as exc:
            rejected.append(f"{company_id}: {exc}")
            continue
        store.save_link_rule(links.company_subject(company_id), links.new_rule("split", clean, set_by))
    typer.echo(f"linked: {len(splits) - len(rejected)}, rejected: {len(rejected)}")
    for line in rejected:
        typer.echo(line, err=True)
    if rejected:
        raise typer.Exit(1)


@links_app.command("classify")
def links_classify(
    portfolio: str = typer.Option(..., "--portfolio"),
    as_of: str = typer.Option(None, "--as-of", help="Default: the portfolio's latest snapshot."),
) -> None:
    """Asks the LLM for an ICIO code for each held company that has no link, and stores it as an `llm` rule."""
    import asyncio

    from arp.cli._shared import _portfolio_store, get_settings
    from arp.llm.factory import build_llm_client
    from arp.research.indirect_exposure.factory import load_model
    from arp.research.value_chain.links import classify_unlinked

    settings, store = get_settings(), _portfolio_store()
    if settings.value_chain_dir is None:
        from arp.research.value_chain.model import NOT_BUILT

        typer.echo(NOT_BUILT, err=True)
        raise typer.Exit(1)
    as_of = as_of or store.latest_snapshot_date(portfolio)
    if as_of is None:
        typer.echo(f"no holdings for '{portfolio}'", err=True)
        raise typer.Exit(1)
    try:
        model = load_model(settings.value_chain_dir)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    classified, unlinked = asyncio.run(classify_unlinked(store, portfolio, as_of, model, build_llm_client(settings)))
    typer.echo(f"{classified} classified, {unlinked} left unlinked")
