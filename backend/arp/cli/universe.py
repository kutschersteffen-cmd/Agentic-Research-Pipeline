from __future__ import annotations

import json
from pathlib import Path

import typer

from arp.cli.theme import _funnel_taxonomy
from arp.golden_set.exposure import load_set
from arp.research.taxonomy_sources.etf_holdings import load_holdings_with_weights, load_universe_from_holdings
from arp.research.taxonomy_sources.overlap import compute_holdings_overlap
from arp.universe import load_company_universe
from arp.universe_narrow import narrow_universe, taxonomy_divisions

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


@universe_app.command("narrow")
def universe_narrow(
    universe: Path = typer.Option(..., help="Company universe CSV or JSON."),
    taxonomy_id: str = typer.Option(..., "--taxonomy", help="The taxonomy whose activity sector codes to keep."),
    taxonomy_version: int = typer.Option(None, "--taxonomy-version", help="Defaults to the latest version."),
    taxonomies_dir: Path = typer.Option(None, "--taxonomies-dir", help="Taxonomy store directory (default: configured)."),
    out: Path = typer.Option(..., help="Where to write the narrowed universe JSON."),
    keep: list[str] = typer.Option([], "--keep", help="A company_id to keep even if its codes don't match (repeatable)."),
    cases: Path = typer.Option(None, "--cases", help="Exposure golden cases.json: print dropped counts per label."),
) -> None:
    """Keeps only companies whose ISIC/NACE code shares an ISIC division with the taxonomy's activity codes, so
    discovery, `documents warm` and the theme run never see out-of-sector companies. Companies without a known
    code are kept; every dropped company is listed with its reason in <out stem>.dropped.json."""
    taxonomy = _funnel_taxonomy(taxonomy_id, taxonomy_version, taxonomies_dir, None)
    companies = load_company_universe(universe)
    if not taxonomy_divisions(taxonomy.theme):
        typer.echo("Taxonomy has no sector codes; nothing narrowed.")
    kept, dropped = narrow_universe(companies, taxonomy.theme, set(keep))
    dropped_path = out.with_name(f"{out.stem}.dropped.json")
    out.write_text(json.dumps([c.model_dump(mode="json") for c in kept], indent=2))
    dropped_path.write_text(json.dumps(dropped, indent=2))
    typer.echo(f"Kept {len(kept)} of {len(companies)} companies; {len(dropped)} dropped (see {dropped_path}).")
    if cases is not None:
        golden = load_set(cases.parent)
        gone = {d["company_id"] for d in dropped}
        present = {c.company_id for c in companies}
        for label in golden.labels:
            ids = [c.case_id for c in golden.cases if c.label == label and c.case_id in present]
            typer.echo(f"{label} dropped: {sum(i in gone for i in ids)}/{len(ids)}")

