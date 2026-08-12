from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.config import get_settings
from arp.discovery.pipeline import run_discovery
from arp.discovery.scheduler import DiscoveryScheduler
from arp.extraction.pipeline import run_extraction
from arp.extraction.schema_builder import draft_schema
from arp.ingestion.edgar import EdgarDocumentSource
from arp.ingestion.local_files import LocalFileDocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.factory import build_llm_client
from arp.research.activity_generator import build_theme
from arp.research.pipeline import run_thematic_universe
from arp.schemas.common import DocType
from arp.schemas.datapoints import DataPointSchema
from arp.schemas.discovery import DiscoveryScheduleConfig
from arp.schemas.thematic import ThemeDefinition
from arp.storage.run_store import RunStore
from arp.universe import load_company_universe

app = typer.Typer(help="Agentic Research Pipeline CLI -- the headless path for 1000s-of-companies batch runs.")
theme_app = typer.Typer(help="Thematic investment universe screening.")
extract_app = typer.Typer(help="Schema-driven data-point extraction.")
discover_app = typer.Typer(help="Document discovery: find and download company disclosures.")
runs_app = typer.Typer(help="Inspect and export runs.")
app.add_typer(theme_app, name="theme")
app.add_typer(extract_app, name="extract")
app.add_typer(discover_app, name="discover")
app.add_typer(runs_app, name="runs")


def _registry() -> DocumentSourceRegistry:
    settings = get_settings()
    return DocumentSourceRegistry(
        [LocalFileDocumentSource(settings.documents_dir), EdgarDocumentSource(settings.edgar_user_agent, settings.cache_dir)]
    )


def _run_store() -> RunStore:
    return RunStore(get_settings().runs_dir)


@theme_app.command("decompose")
def theme_decompose(name: str, description: str = "", out: Path = typer.Option(..., help="Where to write the ThemeDefinition JSON.")) -> None:
    settings = get_settings()
    llm = build_llm_client(settings)
    theme, _usage = asyncio.run(build_theme(name, description, llm))
    out.write_text(theme.model_dump_json(indent=2))
    typer.echo(f"Wrote theme with {len(theme.activities)} activities to {out}")


@theme_app.command("run")
def theme_run(
    theme_file: Path = typer.Option(..., "--theme", help="ThemeDefinition JSON (from `theme decompose` or hand-written)."),
    universe: Path = typer.Option(..., help="Company universe CSV or JSON."),
) -> None:
    settings = get_settings()
    llm = build_llm_client(settings)
    theme = ThemeDefinition.model_validate_json(theme_file.read_text())
    companies = load_company_universe(universe)
    typer.echo(f"Running theme '{theme.name}' against {len(companies)} companies...")
    run_id = asyncio.run(
        run_thematic_universe(theme, companies, llm=llm, registry=_registry(), settings=settings, run_store=_run_store())
    )
    typer.echo(f"Run complete: {run_id} (see runs/{run_id}/)")


@extract_app.command("draft-schema")
def extract_draft_schema(criteria_text: str, out: Path = typer.Option(...)) -> None:
    settings = get_settings()
    llm = build_llm_client(settings)
    schema, _usage = asyncio.run(draft_schema(criteria_text, llm))
    out.write_text(schema.model_dump_json(indent=2))
    typer.echo(f"Wrote schema with {len(schema.fields)} fields to {out}")


@extract_app.command("run")
def extract_run(
    schema_file: Path = typer.Option(..., "--schema"),
    universe: Path = typer.Option(...),
) -> None:
    settings = get_settings()
    llm = build_llm_client(settings)
    schema = DataPointSchema.model_validate_json(schema_file.read_text())
    companies = load_company_universe(universe)
    typer.echo(f"Extracting schema '{schema.name}' ({len(schema.fields)} fields) across {len(companies)} companies...")
    run_id = asyncio.run(
        run_extraction(schema, companies, llm=llm, registry=_registry(), settings=settings, run_store=_run_store())
    )
    typer.echo(f"Run complete: {run_id} (see runs/{run_id}/)")


@discover_app.command("run")
def discover_run(
    universe: Path = typer.Option(...),
    doc_types: str = typer.Option("", help="Comma-separated DocType values; empty = all supported types."),
) -> None:
    settings = get_settings()
    companies = load_company_universe(universe)
    types = [DocType(t.strip()) for t in doc_types.split(",") if t.strip()] or None
    typer.echo(f"Discovering documents for {len(companies)} companies...")
    run_id = asyncio.run(
        run_discovery(companies, settings=settings, run_store=_run_store(), doc_types=types, triggered_by="manual")
    )
    typer.echo(f"Run complete: {run_id} (see runs/{run_id}/, new documents under data/documents/)")


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


@runs_app.command("list")
def runs_list(run_type: str = typer.Option(None)) -> None:
    manifests = _run_store().list_runs(run_type)
    for m in manifests:
        typer.echo(f"{m.run_id}\t{m.run_type}\t{m.status.value}\t{m.completed_count}/{m.company_count} done\t${m.estimated_cost_usd:.2f}")


@runs_app.command("show")
def runs_show(run_id: str) -> None:
    manifest = _run_store().load_manifest(run_id)
    if manifest is None:
        typer.echo("Run not found", err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps(manifest.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    app()
