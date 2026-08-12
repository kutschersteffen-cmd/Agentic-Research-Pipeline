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
from arp.research.activity_generator import build_theme, build_theme_industry_anchored
from arp.research.indirect_exposure.core_sectors import classify_theme_core_sectors
from arp.research.indirect_exposure.factory import build_leontief_model
from arp.research.pipeline import run_thematic_universe
from arp.schemas.common import DocType
from arp.schemas.datapoints import DataPointSchema
from arp.schemas.discovery import DiscoveryScheduleConfig
from arp.schemas.taxonomy import DerivationMethod
from arp.schemas.thematic import ThemeDefinition
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore
from arp.universe import load_company_universe

app = typer.Typer(help="Agentic Research Pipeline CLI -- the headless path for 1000s-of-companies batch runs.")
theme_app = typer.Typer(help="Thematic investment universe screening.")
taxonomy_app = typer.Typer(help="The reusable, versioned taxonomy library.")
extract_app = typer.Typer(help="Schema-driven data-point extraction.")
discover_app = typer.Typer(help="Document discovery: find and download company disclosures.")
runs_app = typer.Typer(help="Inspect and export runs.")
app.add_typer(theme_app, name="theme")
app.add_typer(taxonomy_app, name="taxonomy")
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


def _taxonomy_store() -> TaxonomyStore:
    return TaxonomyStore(get_settings().taxonomies_dir)


@theme_app.command("decompose")
def theme_decompose(name: str, description: str = "", out: Path = typer.Option(..., help="Where to write the ThemeDefinition JSON.")) -> None:
    settings = get_settings()
    llm = build_llm_client(settings)
    theme, _usage = asyncio.run(build_theme(name, description, llm))
    out.write_text(theme.model_dump_json(indent=2))
    typer.echo(f"Wrote theme with {len(theme.activities)} activities to {out}")


@theme_app.command("classify-sectors")
def theme_classify_sectors(
    theme_file: Path = typer.Option(..., "--theme"),
    out: Path = typer.Option(..., help="Where to write the ThemeDefinition JSON with core_isic_codes populated."),
    use_sample_icio: bool = typer.Option(
        False, help="Use the bundled illustrative sample dataset instead of the configured ICIO paths."
    ),
) -> None:
    """Populates each activity's core_isic_codes -- one classification call
    per activity against the input-output model's fixed industry list, run
    once per theme (not per company) before enabling the indirect-exposure
    tier in `theme run --use-sample-icio` / a configured ARP_ICIO_* path.
    """
    settings = get_settings()
    llm = build_llm_client(settings)
    theme = ThemeDefinition.model_validate_json(theme_file.read_text())
    model = build_leontief_model(settings, use_sample=use_sample_icio)
    if model is None:
        typer.echo(
            "No ICIO data available: set ARP_ICIO_MATRIX_PATH/ARP_ICIO_INDUSTRIES_PATH or pass --use-sample-icio.",
            err=True,
        )
        raise typer.Exit(1)
    updated_theme, _usage = asyncio.run(classify_theme_core_sectors(theme, model, llm))
    out.write_text(updated_theme.model_dump_json(indent=2))
    classified = sum(1 for a in updated_theme.activities if a.core_isic_codes)
    typer.echo(f"Classified core sectors for {classified}/{len(updated_theme.activities)} activities. Wrote {out}")


@theme_app.command("run")
def theme_run(
    theme_file: Path = typer.Option(
        None, "--theme", help="ThemeDefinition JSON (from `theme decompose` or hand-written)."
    ),
    taxonomy_id: str = typer.Option(None, "--taxonomy", help="Load a saved taxonomy instead of --theme."),
    taxonomy_version: int = typer.Option(None, "--taxonomy-version", help="Defaults to the latest version."),
    universe: Path = typer.Option(..., help="Company universe CSV or JSON."),
    use_sample_icio: bool = typer.Option(
        False,
        "--use-sample-icio",
        help="Enable the indirect-exposure tier using the bundled illustrative sample dataset (demo only).",
    ),
) -> None:
    settings = get_settings()
    llm = build_llm_client(settings)
    if theme_file is not None:
        theme = ThemeDefinition.model_validate_json(theme_file.read_text())
    elif taxonomy_id is not None:
        taxonomy = _taxonomy_store().get(taxonomy_id, taxonomy_version)
        if taxonomy is None:
            typer.echo(f"Taxonomy not found: {taxonomy_id}", err=True)
            raise typer.Exit(1)
        theme = taxonomy.theme
        typer.echo(f"Using taxonomy {taxonomy.taxonomy_id} v{taxonomy.version} ({taxonomy.status.value}).")
    else:
        typer.echo("Provide either --theme or --taxonomy.", err=True)
        raise typer.Exit(1)
    companies = load_company_universe(universe)
    indirect_model = build_leontief_model(settings, use_sample=use_sample_icio)
    if indirect_model is not None:
        typer.echo(f"Indirect exposure tier enabled ({indirect_model.edition_label}).")
    typer.echo(f"Running theme '{theme.name}' against {len(companies)} companies...")
    run_id = asyncio.run(
        run_thematic_universe(
            theme,
            companies,
            llm=llm,
            registry=_registry(),
            settings=settings,
            run_store=_run_store(),
            indirect_model=indirect_model,
        )
    )
    typer.echo(f"Run complete: {run_id} (see runs/{run_id}/)")


@taxonomy_app.command("create")
def taxonomy_create(
    name: str,
    description: str = "",
    use_sample_icio: bool = typer.Option(
        False, help="Anchor the draft against the bundled illustrative ISIC reference list."
    ),
) -> None:
    """Drafts and saves a new taxonomy (v1) -- a reusable, versioned
    artifact, unlike `theme decompose`'s throwaway JSON file."""
    settings = get_settings()
    llm = build_llm_client(settings)
    if use_sample_icio:
        model = build_leontief_model(settings, use_sample=True)
        assert model is not None
        theme, _usage = asyncio.run(build_theme_industry_anchored(name, description, model.industry_reference_list(), llm))
        method = DerivationMethod.INDUSTRY_ANCHORED
        notes = f"Anchored against {model.edition_label} ({len(model.codes)} industries)."
    else:
        theme, _usage = asyncio.run(build_theme(name, description, llm))
        method = DerivationMethod.LLM_DRAFT
        notes = "Freeform LLM draft, no industry anchor."
    taxonomy = _taxonomy_store().create(name, theme, method, notes)
    typer.echo(f"Created taxonomy {taxonomy.taxonomy_id} v{taxonomy.version} with {len(theme.activities)} activities.")


@taxonomy_app.command("list")
def taxonomy_list() -> None:
    for t in _taxonomy_store().list_all():
        typer.echo(f"{t.taxonomy_id}\tv{t.version}\t{t.status.value}\t{t.derivation_method.value}\t{t.name}")


@taxonomy_app.command("show")
def taxonomy_show(taxonomy_id: str, version: int = typer.Option(None)) -> None:
    taxonomy = _taxonomy_store().get(taxonomy_id, version)
    if taxonomy is None:
        typer.echo("Not found", err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps(taxonomy.model_dump(mode="json"), indent=2))


@taxonomy_app.command("new-version")
def taxonomy_new_version(
    taxonomy_id: str,
    theme_file: Path = typer.Option(..., "--theme", help="Edited ThemeDefinition JSON."),
    notes: str = typer.Option("Manual edit.", "--notes"),
) -> None:
    theme = ThemeDefinition.model_validate_json(theme_file.read_text())
    try:
        taxonomy = _taxonomy_store().new_version(taxonomy_id, theme, DerivationMethod.MANUAL, notes)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Created {taxonomy.taxonomy_id} v{taxonomy.version}")


@taxonomy_app.command("ratify")
def taxonomy_ratify(
    taxonomy_id: str,
    by: str = typer.Option(..., help="Name/identifier of the person ratifying this version."),
    version: int = typer.Option(None, help="Defaults to the latest version."),
) -> None:
    store = _taxonomy_store()
    resolved_version = version
    if resolved_version is None:
        current = store.get(taxonomy_id)
        if current is None:
            typer.echo(f"Taxonomy not found: {taxonomy_id}", err=True)
            raise typer.Exit(1)
        resolved_version = current.version
    try:
        store.ratify(taxonomy_id, resolved_version, by)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Ratified {taxonomy_id} v{resolved_version} by {by}")


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
