from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from arp.cli._shared import _run_store
from arp.config import get_settings
from arp.discovery.pipeline import run_discovery
from arp.discovery.scheduler import DiscoveryScheduler
from arp.schemas.common import DocType
from arp.schemas.discovery import DiscoveryScheduleConfig
from arp.universe import load_company_universe

discover_app = typer.Typer(help="Document discovery: find and download company disclosures.")


@discover_app.command("run")
def discover_run(
    universe: Path = typer.Option(...),
    doc_types: str = typer.Option("", help="Comma-separated DocType values; empty = all supported types."),
) -> None:
    settings = get_settings()
    companies = load_company_universe(universe)
    types = [DocType(t.strip()) for t in doc_types.split(",") if t.strip()] or None
    typer.echo(f"Discovering documents for {len(companies)} companies...")
    run_store = _run_store()
    run_id = asyncio.run(
        run_discovery(companies, settings=settings, run_store=run_store, doc_types=types, triggered_by="manual")
    )
    rows = run_store.read_jsonl(run_store.results_path(run_id))
    unreachable = [r for r in rows if r.get("homepage_unreachable")]
    typer.echo(f"Run complete: {run_id} (see runs/{run_id}/, new documents under data/documents/)")
    if unreachable:
        typer.echo(f"WARNING: {len(unreachable)}/{len(companies)} companies' homepage could not be reached (not the same as \"no documents found\"):", err=True)
        for r in unreachable:
            typer.echo(f"  {r['company_id']}: {r.get('crawl_error')}", err=True)



@discover_app.command("schedule")
def discover_schedule(
    universe: Path = typer.Option(...),
    interval_hours: float = typer.Option(24.0),
    enable: bool = typer.Option(True, help="Pass --no-enable to disable."),
) -> None:
    """Configures the automatic recurring discovery run. Takes effect the
    next time the API server process starts (it owns the scheduler); this
    command just persists the config file the scheduler reads."""
    settings = get_settings()
    scheduler = DiscoveryScheduler(settings, _run_store())
    config = DiscoveryScheduleConfig(enabled=enable, interval_hours=interval_hours, universe_path=str(universe))
    scheduler.save_config(config)
    typer.echo(f"Schedule saved: enabled={enable}, every {interval_hours}h, universe={universe}")
