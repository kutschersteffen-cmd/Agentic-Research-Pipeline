from __future__ import annotations

import json
from pathlib import Path

import typer

from arp.research.taxonomy_sources.etf_holdings import load_holdings_with_weights, load_universe_from_holdings
from arp.research.taxonomy_sources.overlap import compute_holdings_overlap

universe_app = typer.Typer(help="Build reusable company universes.")


@universe_app.command("from-holdings")
def universe_from_holdings(
    holdings: Path,
    out: Path = typer.Option(..., help="Where to write the normalized universe JSON."),
) -> None:
    """Builds a company universe from a fund/index holdings export (a
    sector SPDR, a broad index ETF, ...) instead of a hand-written list --
    reuses the same holdings CSV parser the etf_index_holdings taxonomy
    method uses."""
    companies = load_universe_from_holdings(holdings)
    if not companies:
        typer.echo(f"No usable rows found in {holdings}", err=True)
        raise typer.Exit(1)
    out.write_text(json.dumps([c.model_dump(mode="json") for c in companies], indent=2))
    typer.echo(f"Wrote {len(companies)} companies to {out}")



@universe_app.command("overlap")
def universe_overlap(
    holdings: list[Path] = typer.Argument(..., help="Two or more holdings CSVs to compare."),
    names: list[str] = typer.Option(None, "--name", help="Display name per file, in order (defaults to filenames)."),
) -> None:
    """Computes deterministic holdings overlap across two or more funds --
    pure set/weight math, no LLM."""
    if len(holdings) < 2:
        typer.echo("Provide at least two holdings files.", err=True)
        raise typer.Exit(1)
    fund_names = names or [p.stem for p in holdings]
    if len(fund_names) != len(holdings):
        typer.echo("--name count must match the number of holdings files.", err=True)
        raise typer.Exit(1)
    fund_holdings = {name: load_holdings_with_weights(path) for name, path in zip(fund_names, holdings, strict=True)}
    result = compute_holdings_overlap(fund_holdings)
    typer.echo(json.dumps(result.model_dump(mode="json"), indent=2))
