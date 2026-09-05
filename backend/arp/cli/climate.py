from __future__ import annotations

import json

import typer

from arp.cli._shared import _portfolio_directories, _portfolio_store
from arp.portfolio.climate import metrics as climate_metrics

climate_app = typer.Typer(help="Portfolio climate analytics: WACI, financed emissions, coverage.")


@climate_app.command("waci")
def climate_waci(
    group_by: str = typer.Option("portfolio_id"),
    portfolio: list[str] = typer.Option(None, "--portfolio"),
    as_of: str = typer.Option(None),
) -> None:
    store = _portfolio_store()
    securities, companies = _portfolio_directories(store)
    dates = store.all_snapshot_dates()
    resolved_as_of = as_of or (dates[-1] if dates else None)
    if resolved_as_of is None:
        typer.echo("No holdings snapshots available -- run `arp portfolio seed-demo` first.", err=True)
        raise typer.Exit(1)
    holdings = store.load_holdings_as_of(resolved_as_of, portfolio or None)
    result = climate_metrics.compute_waci(
        store, holdings, securities, companies, as_of=resolved_as_of, group_by=group_by, portfolio_filter=portfolio or None
    )
    typer.echo(json.dumps(result.model_dump(mode="json"), indent=2))



@climate_app.command("financed-emissions")
def climate_financed_emissions(
    portfolio: list[str] = typer.Option(None, "--portfolio"), as_of: str = typer.Option(None)
) -> None:
    store = _portfolio_store()
    securities, _companies = _portfolio_directories(store)
    dates = store.all_snapshot_dates()
    resolved_as_of = as_of or (dates[-1] if dates else None)
    if resolved_as_of is None:
        typer.echo("No holdings snapshots available -- run `arp portfolio seed-demo` first.", err=True)
        raise typer.Exit(1)
    holdings = store.load_holdings_as_of(resolved_as_of, portfolio or None)
    result = climate_metrics.compute_financed_emissions(
        store, holdings, securities, as_of=resolved_as_of, portfolio_filter=portfolio or None
    )
    typer.echo(json.dumps(result, indent=2))



@climate_app.command("coverage")
def climate_coverage(field_id: str, as_of: str = typer.Option(None)) -> None:
    store = _portfolio_store()
    securities, _companies = _portfolio_directories(store)
    result = climate_metrics.coverage_report(store, securities, field_id, as_of)
    typer.echo(json.dumps(result, indent=2))
