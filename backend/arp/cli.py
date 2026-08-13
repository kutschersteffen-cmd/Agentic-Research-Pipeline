from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.config import get_settings
from arp.discovery.pipeline import run_discovery
from arp.discovery.scheduler import DiscoveryScheduler
from arp.discovery.site_finder import DuckDuckGoSearchClient
from arp.extraction.pipeline import run_extraction
from arp.extraction.schema_builder import draft_schema
from arp.ingestion.edgar import EdgarDocumentSource
from arp.ingestion.local_files import LocalFileDocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.factory import build_llm_client
from arp.research.activity_generator import build_theme, build_theme_industry_anchored
from arp.research.indirect_exposure.core_sectors import classify_theme_core_sectors
from arp.research.indirect_exposure.factory import build_leontief_model
from arp.research.pipeline import resume_theme_run, run_thematic_universe
from arp.research.taxonomy_sources.authority import build_theme_from_authority_sources
from arp.research.taxonomy_sources.compare import compare_taxonomies, merge_taxonomies
from arp.research.taxonomy_sources.discovery import discover_authority_sources, discover_thematic_funds
from arp.research.taxonomy_sources.empirical import build_theme_empirical
from arp.research.taxonomy_sources.etf_holdings import (
    build_theme_from_holdings,
    load_holdings_with_weights,
    load_universe_from_holdings,
)
from arp.research.taxonomy_sources.overlap import compute_holdings_overlap
from arp.research.taxonomy_sources.news_mining import build_theme_from_news_and_transcripts
from arp.research.standards_mapping.mapper import format_standards_csv, map_theme_to_standards
from arp.research.revenue_exposure.catalogue import distinct_labels, load_catalogue, by_company as catalogue_by_company
from arp.research.revenue_exposure.mapping import suggest_catalogue_mapping
from arp.research.revenue_exposure.resolver import RevenueResolverContext
from arp.schemas.revenue_exposure import ActivityCatalogueMapping
from arp.orchestration.job_manager import JobManager
from arp.portfolio import analytics, qa_agent
from arp.portfolio.climate import metrics as climate_metrics
from arp.portfolio.mock_data import generate_demo_dataset
from arp.portfolio.news.classifier import classify_article
from arp.schemas.common import CompanyRef, DocType, JobStatus
from arp.schemas.datapoints import DataPointSchema
from arp.schemas.discovery import DiscoveryScheduleConfig
from arp.schemas.portfolio import AggregationResult, AnalyticSpec, SecurityRef
from arp.schemas.taxonomy import DerivationMethod, TaxonomyRef
from arp.schemas.thematic import ThemeDefinition
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore
from arp.universe import load_company_universe

app = typer.Typer(help="Agentic Research Pipeline CLI -- the headless path for 1000s-of-companies batch runs.")
theme_app = typer.Typer(help="Thematic investment universe screening.")
taxonomy_app = typer.Typer(help="The reusable, versioned taxonomy library.")
extract_app = typer.Typer(help="Schema-driven data-point extraction.")
discover_app = typer.Typer(help="Document discovery: find and download company disclosures.")
runs_app = typer.Typer(help="Inspect and export runs.")
universe_app = typer.Typer(help="Build reusable company universes.")
revenue_catalogue_app = typer.Typer(help="Structured revenue/capex data catalogue mapping.")
portfolio_app = typer.Typer(help="Portfolio holdings aggregation, analytics, and NL Q&A.")
climate_app = typer.Typer(help="Portfolio climate analytics: WACI, financed emissions, coverage.")
app.add_typer(theme_app, name="theme")
app.add_typer(taxonomy_app, name="taxonomy")
app.add_typer(extract_app, name="extract")
app.add_typer(discover_app, name="discover")
app.add_typer(runs_app, name="runs")
app.add_typer(universe_app, name="universe")
app.add_typer(revenue_catalogue_app, name="revenue-catalogue")
app.add_typer(portfolio_app, name="portfolio")
app.add_typer(climate_app, name="climate")


def _registry() -> DocumentSourceRegistry:
    settings = get_settings()
    return DocumentSourceRegistry(
        [LocalFileDocumentSource(settings.documents_dir), EdgarDocumentSource(settings.edgar_user_agent, settings.cache_dir)]
    )


def _run_store() -> RunStore:
    return RunStore(get_settings().runs_dir)


def _taxonomy_store() -> TaxonomyStore:
    return TaxonomyStore(get_settings().taxonomies_dir)


def _portfolio_store() -> PortfolioStore:
    return PortfolioStore(get_settings().portfolios_dir)


def _portfolio_directories(store: PortfolioStore) -> tuple[dict[str, SecurityRef], dict[str, CompanyRef]]:
    securities = {s.security_id: s for s in store.list_securities()}
    companies = {c.company_id: c for c in store.list_companies()}
    return securities, companies


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
    revenue_catalogue: Path = typer.Option(
        None, "--revenue-catalogue", help="A structured revenue/capex catalogue CSV (see `revenue-catalogue suggest-mapping`)."
    ),
    catalogue_mapping: Path = typer.Option(
        None, "--catalogue-mapping", help="The reviewed activity->catalogue-label mapping JSON (required alongside --revenue-catalogue)."
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

    if bool(revenue_catalogue) != bool(catalogue_mapping):
        typer.echo("Provide both --revenue-catalogue and --catalogue-mapping together, or neither.", err=True)
        raise typer.Exit(1)
    revenue_resolver = None
    mappings: list[ActivityCatalogueMapping] | None = None
    if revenue_catalogue is not None:
        catalogue = load_catalogue(revenue_catalogue)
        mappings = [ActivityCatalogueMapping.model_validate(m) for m in json.loads(catalogue_mapping.read_text())]
        revenue_resolver = RevenueResolverContext(
            catalogue_by_company=catalogue_by_company(catalogue), mappings=mappings, registry=_registry(), settings=settings, isic_model=indirect_model
        )
        typer.echo(f"Revenue-exposure resolution enabled ({len(mappings)} confirmed activity mapping(s)).")

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
            revenue_resolver=revenue_resolver,
            universe_path=str(universe),
            use_sample_icio=use_sample_icio,
            revenue_catalogue_path=str(revenue_catalogue) if revenue_catalogue else None,
            catalogue_mapping=mappings,
        )
    )
    typer.echo(f"Run complete: {run_id} (see runs/{run_id}/)")


@theme_app.command("resume")
def theme_resume(run_id: str) -> None:
    """Re-invokes a theme run that was interrupted, failed, partially
    completed, or cancelled -- reconstructed from what `theme run`
    persisted at creation time. Already-completed companies are skipped
    automatically."""
    settings = get_settings()
    llm = build_llm_client(settings)
    try:
        run_id = asyncio.run(resume_theme_run(run_id, llm=llm, registry=_registry(), settings=settings, run_store=_run_store()))
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Resumed run complete: {run_id} (see runs/{run_id}/)")


@taxonomy_app.command("discover-sources")
def taxonomy_discover_sources(
    name: str,
    out: Path = typer.Option(None, help="Optional: write the discovered candidates as JSON instead of printing them."),
) -> None:
    """Web-searches for candidate authority sources (official taxonomies,
    standards bodies) and existing thematic ETFs/indices for this theme --
    the research step, so you can review and pick real sources before
    running a derivation with --method authority_source or
    --method etf_index_holdings."""
    settings = get_settings()
    search_client = DuckDuckGoSearchClient(settings.discovery_user_agent)

    async def _run():
        return await discover_authority_sources(name, search_client), await discover_thematic_funds(name, search_client)

    authority, funds = asyncio.run(_run())

    if out:
        payload = {
            "authority_sources": [a.model_dump(mode="json") for a in authority],
            "thematic_funds": [f.model_dump(mode="json") for f in funds],
        }
        out.write_text(json.dumps(payload, indent=2))
        typer.echo(f"Wrote {len(authority)} authority source(s) and {len(funds)} fund(s) to {out}")
        return

    typer.echo("Authority sources:")
    for a in authority:
        typer.echo(f"  {a.url}\n    {a.name}")
    typer.echo("\nThematic funds/indices:")
    for f in funds:
        typer.echo(f"  {f.url}\n    {f.name}")
    typer.echo(
        "\nFor --method etf_index_holdings, download a holdings export (CSV) from the fund provider's site for "
        "one of the funds above, then pass it via --holdings."
    )


@taxonomy_app.command("create")
def taxonomy_create(
    name: str,
    description: str = "",
    method: DerivationMethod = typer.Option(DerivationMethod.LLM_DRAFT, "--method", help="How to derive this taxonomy."),
    use_sample_icio: bool = typer.Option(
        False, help="[industry_anchored] Anchor against the bundled illustrative ISIC reference list."
    ),
    authority_url: list[str] = typer.Option(
        [], "--authority-url", help="[authority_source] One or more source URLs (repeatable). See `taxonomy discover-sources`."
    ),
    universe: Path = typer.Option(
        None, help="[empirical, news_transcript_mining] A sample company universe CSV/JSON."
    ),
    sample_size: int = typer.Option(25, help="[empirical] How many companies from --universe to sample."),
    holdings: Path = typer.Option(
        None, help="[etf_index_holdings] A fund/index holdings CSV export. See `taxonomy discover-sources`."
    ),
) -> None:
    """Drafts and saves a new taxonomy (v1) -- a reusable, versioned
    artifact, unlike `theme decompose`'s throwaway JSON file. Pick a
    derivation --method; each has its own required inputs (see the option
    help above)."""
    settings = get_settings()
    llm = build_llm_client(settings)

    if method == DerivationMethod.LLM_DRAFT:
        theme, _usage = asyncio.run(build_theme(name, description, llm))
        notes = "Freeform LLM draft, no industry anchor."

    elif method == DerivationMethod.INDUSTRY_ANCHORED:
        model = build_leontief_model(settings, use_sample=use_sample_icio)
        if model is None:
            typer.echo("No ICIO data available: set ARP_ICIO_MATRIX_PATH/ARP_ICIO_INDUSTRIES_PATH or pass --use-sample-icio.", err=True)
            raise typer.Exit(1)
        theme, _usage = asyncio.run(build_theme_industry_anchored(name, description, model.industry_reference_list(), llm))
        notes = f"Anchored against {model.edition_label} ({len(model.codes)} industries)."

    elif method == DerivationMethod.AUTHORITY_SOURCE:
        if not authority_url:
            typer.echo("Provide at least one --authority-url (see `arp taxonomy discover-sources`).", err=True)
            raise typer.Exit(1)
        theme, notes, _usage = asyncio.run(
            build_theme_from_authority_sources(name, description, authority_url, llm, settings.discovery_user_agent)
        )

    elif method == DerivationMethod.EMPIRICAL:
        if universe is None:
            typer.echo("Provide --universe (a sample company list) for --method empirical.", err=True)
            raise typer.Exit(1)
        companies = load_company_universe(universe)
        theme, notes, _usage = asyncio.run(
            build_theme_empirical(name, description, companies, _registry(), llm, settings, sample_size)
        )

    elif method == DerivationMethod.NEWS_TRANSCRIPT_MINING:
        companies = load_company_universe(universe) if universe else None
        search_client = DuckDuckGoSearchClient(settings.discovery_user_agent)
        theme, notes, _usage = asyncio.run(
            build_theme_from_news_and_transcripts(
                name, description, llm, search_client=search_client, companies=companies,
                registry=_registry() if companies else None,
            )
        )

    elif method == DerivationMethod.ETF_INDEX_HOLDINGS:
        if holdings is None:
            typer.echo("Provide --holdings (a fund/index holdings CSV; see `arp taxonomy discover-sources`).", err=True)
            raise typer.Exit(1)
        theme, notes, _usage = asyncio.run(build_theme_from_holdings(name, description, holdings, llm))

    else:
        typer.echo("--method manual has nothing to draft; use `arp taxonomy new-version` to save a hand-written theme.", err=True)
        raise typer.Exit(1)

    taxonomy = _taxonomy_store().create(name, theme, method, notes)
    typer.echo(f"Created taxonomy {taxonomy.taxonomy_id} v{taxonomy.version} ({method.value}) with {len(theme.activities)} activities.")
    typer.echo(notes)


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


def _parse_taxonomy_ref(ref: str) -> TaxonomyRef:
    """Parses 'tax_xxx' or 'tax_xxx:3' (id, or id:version)."""
    if ":" in ref:
        taxonomy_id, version_str = ref.rsplit(":", 1)
        return TaxonomyRef(taxonomy_id=taxonomy_id, version=int(version_str))
    return TaxonomyRef(taxonomy_id=ref, version=None)


def _resolve_taxonomy_ref_or_exit(ref_str: str):
    store = _taxonomy_store()
    ref = _parse_taxonomy_ref(ref_str)
    taxonomy = store.get(ref.taxonomy_id, ref.version)
    if taxonomy is None:
        typer.echo(f"Taxonomy not found: {ref_str}", err=True)
        raise typer.Exit(1)
    return taxonomy


@taxonomy_app.command("compare")
def taxonomy_compare(ref_a: str, ref_b: str) -> None:
    """Diffs two taxonomies' activity sets. Refs are 'taxonomy_id' (latest
    version) or 'taxonomy_id:version'."""
    settings = get_settings()
    llm = build_llm_client(settings)
    taxonomy_a = _resolve_taxonomy_ref_or_exit(ref_a)
    taxonomy_b = _resolve_taxonomy_ref_or_exit(ref_b)
    comparison, _usage = asyncio.run(compare_taxonomies(taxonomy_a, taxonomy_b, llm))
    typer.echo(json.dumps(comparison.model_dump(mode="json"), indent=2))


@taxonomy_app.command("merge")
def taxonomy_merge(
    refs: list[str] = typer.Argument(..., help="Two or more taxonomy refs ('id' or 'id:version')."),
    name: str = typer.Option(..., help="Name for the merged taxonomy."),
    description: str = typer.Option(""),
    out: Path = typer.Option(..., help="Where to write the merged ThemeDefinition JSON (a draft -- review before saving)."),
) -> None:
    if len(refs) < 2:
        typer.echo("Provide at least two taxonomy refs to merge.", err=True)
        raise typer.Exit(1)
    settings = get_settings()
    llm = build_llm_client(settings)
    taxonomies = [_resolve_taxonomy_ref_or_exit(r) for r in refs]
    theme, notes, _usage = asyncio.run(merge_taxonomies(taxonomies, name, description, llm))
    out.write_text(theme.model_dump_json(indent=2))
    typer.echo(f"Wrote merged draft ({len(theme.activities)} activities) to {out}")
    typer.echo(notes)
    typer.echo(f"Review and save with: arp taxonomy new-version <existing_id> --theme {out}  (or create a new taxonomy from it)")


@taxonomy_app.command("map-standards")
def taxonomy_map_standards(
    ref: str,
    use_sample_icio: bool = typer.Option(
        False, help="Classify any activity missing core_isic_codes using the bundled sample ICIO dataset first."
    ),
    use_sample_standards: bool = typer.Option(
        False, help="Use the bundled illustrative NACE/NAICS/SIC/GICS reference data instead of configured ARP_*_PATH files."
    ),
    no_save: bool = typer.Option(False, "--no-save", help="Print the mapping without saving a new taxonomy version."),
) -> None:
    """Cross-references every activity's core_isic_codes into NACE, NAICS,
    SIC (deterministic crosswalk) and GICS (closed-list LLM classification,
    since no official ISIC->GICS correspondence table exists). Saves the
    result as a new taxonomy version unless --no-save is passed."""
    settings = get_settings()
    llm = build_llm_client(settings)
    taxonomy = _resolve_taxonomy_ref_or_exit(ref)
    updated_theme, _usage = asyncio.run(
        map_theme_to_standards(taxonomy.theme, settings, llm, use_sample_icio=use_sample_icio, use_sample_standards=use_sample_standards)
    )
    mapped = sum(1 for a in updated_theme.activities if a.standards_mapping)
    typer.echo(f"Mapped standards for {mapped}/{len(updated_theme.activities)} activities.")
    if no_save:
        typer.echo(updated_theme.model_dump_json(indent=2))
        return
    saved = _taxonomy_store().new_version(
        taxonomy.taxonomy_id, updated_theme, DerivationMethod.MANUAL, "Standards mapping added: NACE, NAICS, SIC (ISIC crosswalk), GICS (LLM-classified)."
    )
    typer.echo(f"Saved {saved.taxonomy_id} v{saved.version}")


@taxonomy_app.command("export-standards")
def taxonomy_export_standards(ref: str, out: Path = typer.Option(..., help="Where to write the standards-mapping CSV.")) -> None:
    """Exports the activity -> NACE/NAICS/SIC/GICS mapping already saved on
    a taxonomy (run `taxonomy map-standards` first) as a flat CSV."""
    taxonomy = _resolve_taxonomy_ref_or_exit(ref)
    out.write_text(format_standards_csv(taxonomy.theme))
    typer.echo(f"Wrote {out}")


@revenue_catalogue_app.command("suggest-mapping")
def revenue_catalogue_suggest_mapping(
    taxonomy_ref: str,
    catalogue_file: Path = typer.Argument(..., help="A structured revenue/capex catalogue CSV."),
    out: Path = typer.Option(..., help="Where to write the draft activity->catalogue-label mapping JSON (review before use)."),
) -> None:
    """Proposes which catalogue labels represent each taxonomy activity's
    revenue/capex, for both metrics -- a draft only; review/edit the output
    file, then pass it to `theme run --catalogue-mapping`. Never applied
    automatically."""
    settings = get_settings()
    llm = build_llm_client(settings)
    taxonomy = _resolve_taxonomy_ref_or_exit(taxonomy_ref)
    catalogue = load_catalogue(catalogue_file)
    labels_by_metric = {"revenue": distinct_labels(catalogue, "revenue"), "capex": distinct_labels(catalogue, "capex")}
    mappings, _usage = asyncio.run(suggest_catalogue_mapping(taxonomy.theme, labels_by_metric, llm))
    out.write_text(json.dumps([m.model_dump(mode="json") for m in mappings], indent=2))
    typer.echo(f"Wrote {len(mappings)} proposed mapping(s) to {out}. Review before using with `theme run --catalogue-mapping`.")


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


@runs_app.command("list")
def runs_list(run_type: str = typer.Option(None)) -> None:
    manifests = _run_store().list_runs(run_type)
    for m in manifests:
        typer.echo(f"{m.run_id}\t{m.run_type}\t{m.status.value}\t{m.completed_count}/{m.company_count} done\t${m.estimated_cost_usd:.2f}")


@runs_app.command("cancel")
def runs_cancel(run_id: str) -> None:
    """Requests a cooperative stop for a running/pending run -- in-flight
    items still finish and checkpoint; no new ones start. Works for any
    run type. Resume it later with `arp theme resume` (theme runs only)."""
    store = _run_store()
    manifest = store.load_manifest(run_id)
    if manifest is None:
        typer.echo("Run not found", err=True)
        raise typer.Exit(1)
    if manifest.status not in (JobStatus.RUNNING, JobStatus.PENDING):
        typer.echo(f"Run {run_id} is already {manifest.status.value} -- nothing to cancel.", err=True)
        raise typer.Exit(1)
    JobManager(store).request_cancel(run_id)
    typer.echo(f"Cancellation requested for {run_id}.")


@runs_app.command("show")
def runs_show(run_id: str) -> None:
    manifest = _run_store().load_manifest(run_id)
    if manifest is None:
        typer.echo("Run not found", err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps(manifest.model_dump(mode="json"), indent=2))


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
    fund_holdings = {name: load_holdings_with_weights(path) for name, path in zip(fund_names, holdings)}
    result = compute_holdings_overlap(fund_holdings)
    typer.echo(json.dumps(result.model_dump(mode="json"), indent=2))


@portfolio_app.command("seed-demo")
def portfolio_seed_demo() -> None:
    """Seeds the built-in illustrative multi-portfolio demo dataset (see
    arp/portfolio/mock_data.py): companies, securities (incl. one
    deliberately unresolved instrument), 4 quarterly holdings snapshots
    across 4 portfolios, climate data-point observations with a validated
    internal-API/extraction cross-check, and ingested news items.
    Deterministic and safe to re-run.
    """
    settings = get_settings()
    summary = asyncio.run(
        generate_demo_dataset(_portfolio_store(), settings.portfolio_confidence_review_threshold, settings.climate_validation_tolerance_pct)
    )
    typer.echo(json.dumps(summary.__dict__, indent=2))


@portfolio_app.command("list")
def portfolio_list() -> None:
    for p in _portfolio_store().list_portfolios():
        typer.echo(f"{p.portfolio_id}\t{p.name}\t{','.join(p.tags)}")


@portfolio_app.command("review-queue")
def portfolio_review_queue() -> None:
    """Securities whose issuer entity resolution fell below the confidence
    threshold -- never auto-matched, always surfaced here instead."""
    rows = _portfolio_store().list_resolutions_needing_review()
    if not rows:
        typer.echo("Nothing pending review.")
        return
    for r in rows:
        typer.echo(f"{r.security_id}\tbest_guess_company_id={r.company_id}\tconfidence={r.confidence:.2f}\tmethod={r.method}")


@portfolio_app.command("aggregate")
def portfolio_aggregate(
    group_by: str = typer.Option(..., help="portfolio_id | asset_class | company_id | company_name | sector | country | currency"),
    metric: str = typer.Option("market_value_sum", help="market_value_sum | weighted_avg_datapoint | count"),
    portfolio: list[str] = typer.Option(None, "--portfolio", help="Restrict to these portfolio_ids; repeatable."),
    company_id: str = typer.Option(None, help="Filter to one issuer, e.g. bmw."),
    asset_class: str = typer.Option(None),
    data_point_field_id: str = typer.Option(None, help="Required for metric=weighted_avg_datapoint, e.g. climate_carbon_intensity."),
    as_of: str = typer.Option(None, help="Snapshot date; defaults to the latest available."),
    name: str = typer.Option("cli query"),
) -> None:
    """Runs a query against the deterministic aggregation engine -- the
    same "how many EUR million exposure to BMW" primitive the API and the
    NL Q&A agent both use underneath."""
    store = _portfolio_store()
    security_filter: dict[str, str] = {}
    if company_id:
        security_filter["company_id"] = company_id
    if asset_class:
        security_filter["asset_class"] = asset_class
    spec = AnalyticSpec(
        name=name, portfolio_filter=portfolio or [], security_filter=security_filter, group_by=group_by,
        metric=metric, data_point_field_id=data_point_field_id, as_of=as_of,
    )
    securities, companies = _portfolio_directories(store)
    try:
        result = analytics.execute(spec, store, securities, companies)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if isinstance(result, AggregationResult):
        typer.echo(json.dumps(result.model_dump(mode="json"), indent=2))
    else:
        typer.echo(json.dumps([point.model_dump(mode="json") for point in result], indent=2))


@portfolio_app.command("ask")
def portfolio_ask(question: str) -> None:
    """Answers a plain-language portfolio question end to end: the LLM
    only drafts a query, the deterministic engine computes it, and the
    printed answer shows the real numbers behind it. Requires
    ARP_ANTHROPIC_API_KEY."""
    llm = build_llm_client(get_settings())
    store = _portfolio_store()
    securities, companies = _portfolio_directories(store)
    answer, _usage = asyncio.run(qa_agent.answer_question(question, llm, store, securities, companies))
    if not answer.resolvable:
        typer.echo(f"Could not resolve the question: {answer.clarification_needed}")
        raise typer.Exit(1)
    typer.echo(answer.answer_text)


@portfolio_app.command("classify-news")
def portfolio_classify_news() -> None:
    """Runs the LLM risk classifier over ingested, not-yet-classified news
    items and persists any resulting grounded risk flags. Requires
    ARP_ANTHROPIC_API_KEY."""
    llm = build_llm_client(get_settings())
    store = _portfolio_store()
    already_classified = {f.news_id for f in store.list_flags()}
    pending = [item for item in store.list_news() if item.news_id not in already_classified]

    async def _run() -> int:
        created = 0
        for item in pending:
            flag, _usage = await classify_article(item, llm)
            if flag is not None:
                store.append_flag(flag)
                created += 1
        return created

    created = asyncio.run(_run())
    typer.echo(f"Classified {len(pending)} article(s), created {created} risk flag(s).")


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


if __name__ == "__main__":
    app()
