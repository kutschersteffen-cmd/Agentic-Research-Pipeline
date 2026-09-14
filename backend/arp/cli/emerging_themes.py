from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.cli._shared import _run_store, _taxonomy_store, _topic_store
from arp.config import get_settings
from arp.emerging_themes.pipeline import load_candidates_with_status, promote_candidate, reject_candidate, run_emerging_themes
from arp.emerging_themes.scheduler import EmergingThemesScheduler, default_sources
from arp.llm.factory import build_llm_client
from arp.schemas.emerging_themes import EmergingThemesScheduleConfig
from arp.universe import load_company_universe

emerging_themes_app = typer.Typer(help="Emerging Themes Scanner ('Tool 0'): bottom-up candidate-theme discovery from public news/filings/regulatory flow, feeding the taxonomy library.")


@emerging_themes_app.command("run")
def emerging_themes_run(universe: Path = typer.Option(...)) -> None:
    """Scans public news/filings/regulatory flow across the universe for
    emerging themes: Ingest -> Extract -> Detect (cluster + lineage) ->
    Synthesize -> Validate -> Output. Requires ARP_ANTHROPIC_API_KEY and
    the `emerging_themes` extra (pip install -e '.[emerging_themes]')."""
    settings = get_settings()
    companies = load_company_universe(universe)
    llm = build_llm_client(settings)
    typer.echo(f"Scanning for emerging themes across {len(companies)} companies...")
    run_id = asyncio.run(
        run_emerging_themes(
            companies, llm=llm, sources=default_sources(settings), settings=settings,
            run_store=_run_store(), topic_store=_topic_store(), triggered_by="manual",
        )
    )
    candidates = load_candidates_with_status(_run_store(), run_id)
    typer.echo(f"Run complete: {run_id} -- {len(candidates)} candidate theme(s). See `arp emerging-themes candidates {run_id}`.")



@emerging_themes_app.command("candidates")
def emerging_themes_candidates(run_id: str) -> None:
    candidates = load_candidates_with_status(_run_store(), run_id)
    if not candidates:
        typer.echo("No candidates for this run.")
        return
    for c in candidates:
        typer.echo(f"{c.theme_id}\t{c.status.value}\tconf={c.confidence_score:.2f}\t{c.theme_name}")



@emerging_themes_app.command("show")
def emerging_themes_show(run_id: str, theme_id: str) -> None:
    candidates = load_candidates_with_status(_run_store(), run_id)
    candidate = next((c for c in candidates if c.theme_id == theme_id), None)
    if candidate is None:
        typer.echo("Not found", err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps(candidate.model_dump(mode="json"), indent=2))



@emerging_themes_app.command("promote")
def emerging_themes_promote(
    run_id: str,
    theme_id: str,
    taxonomy_id: str = typer.Option(None, help="Extend an existing ratified taxonomy instead of creating a new one."),
) -> None:
    """The human review gate: promotes one surviving candidate into the
    taxonomy DRAFT/ratify workflow. No candidate reaches the taxonomy
    library without this explicit call."""
    settings = get_settings()
    llm = build_llm_client(settings)
    try:
        candidate = asyncio.run(
            promote_candidate(_run_store(), _taxonomy_store(), llm, run_id, theme_id, taxonomy_id=taxonomy_id)
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Promoted {theme_id} -> taxonomy {candidate.promoted_to_taxonomy_id} v{candidate.promoted_to_taxonomy_version} (DRAFT -- ratify via `arp taxonomy ratify`).")



@emerging_themes_app.command("reject")
def emerging_themes_reject(run_id: str, theme_id: str) -> None:
    reject_candidate(_run_store(), run_id, theme_id)
    typer.echo(f"Rejected {theme_id}.")



@emerging_themes_app.command("schedule")
def emerging_themes_schedule(
    universe: Path = typer.Option(...),
    interval_hours: float = typer.Option(168.0, help="Weekly by default -- matches the lineage-tracking window."),
    enable: bool = typer.Option(True, help="Pass --no-enable to disable."),
) -> None:
    """Configures the automatic recurring scan. Takes effect the next time
    the API server process starts (it owns the scheduler); this command
    just persists the config file the scheduler reads."""
    settings = get_settings()
    scheduler = EmergingThemesScheduler(settings, _run_store(), _topic_store(), llm_factory=lambda: build_llm_client(settings))
    config = EmergingThemesScheduleConfig(enabled=enable, interval_hours=interval_hours, universe_path=str(universe))
    scheduler.save_config(config)
    typer.echo(f"Schedule saved: enabled={enable}, every {interval_hours}h, universe={universe}")
