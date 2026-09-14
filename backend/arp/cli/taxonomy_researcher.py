from __future__ import annotations

import asyncio

import typer

from arp.agents.taxonomy_researcher import TaxonomyResearcherScheduler, run_taxonomy_research
from arp.cli._shared import _run_store, _taxonomy_store
from arp.config import get_settings
from arp.discovery.site_finder import DuckDuckGoSearchClient
from arp.llm.factory import build_llm_client
from arp.schemas.taxonomy_researcher import TaxonomyResearcherScheduleConfig

taxonomy_researcher_app = typer.Typer(help="Standing agent: periodically re-scans ratified taxonomies' authority sources, proposing new DRAFT versions -- never auto-ratifies.")


@taxonomy_researcher_app.command("run")
def taxonomy_researcher_run(
    taxonomy_ids: str = typer.Option("", help="Comma-separated taxonomy_ids to scope to; empty = every ratified taxonomy."),
) -> None:
    """Scans ratified taxonomies for authority-source updates and proposes
    new DRAFT versions -- never auto-ratifies. Uses the exact same
    pipeline the automatic schedule uses."""
    settings = get_settings()
    llm = build_llm_client(settings)
    ids = [t.strip() for t in taxonomy_ids.split(",") if t.strip()] or None
    run_store = _run_store()
    run_id = asyncio.run(
        run_taxonomy_research(
            llm=llm, search_client=DuckDuckGoSearchClient(settings.discovery_user_agent), settings=settings,
            taxonomy_store=_taxonomy_store(), run_store=run_store, taxonomy_ids=ids, triggered_by="manual",
        )
    )
    rows = run_store.read_jsonl(run_store.results_path(run_id))
    proposed = [r for r in rows if r.get("proposed")]
    typer.echo(f"Run complete: {run_id} -- scanned {len(rows)} taxonomy/ies, proposed {len(proposed)} new version(s).")



@taxonomy_researcher_app.command("schedule")
def taxonomy_researcher_schedule(
    interval_hours: float = typer.Option(168.0, help="Weekly by default."),
    taxonomy_ids: str = typer.Option("", help="Comma-separated taxonomy_ids to scope to; empty = every ratified taxonomy."),
    enable: bool = typer.Option(True, help="Pass --no-enable to disable."),
) -> None:
    """Configures the automatic recurring taxonomy research scan. Takes
    effect the next time the API server process starts (it owns the
    scheduler); this command just persists the config file it reads."""
    settings = get_settings()
    ids = [t.strip() for t in taxonomy_ids.split(",") if t.strip()] or None
    scheduler = TaxonomyResearcherScheduler(settings, _run_store(), _taxonomy_store(), lambda: build_llm_client(settings), DuckDuckGoSearchClient(settings.discovery_user_agent))
    config = TaxonomyResearcherScheduleConfig(enabled=enable, interval_hours=interval_hours, taxonomy_ids=ids)
    scheduler.save_config(config)
    typer.echo(f"Schedule saved: enabled={enable}, every {interval_hours}h, taxonomy_ids={ids or 'all ratified'}")
