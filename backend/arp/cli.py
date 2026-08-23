from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.config import get_settings
from arp.discovery.identity_pipeline import enriched_universe, run_identity_resolution
from arp.discovery.pipeline import run_discovery
from arp.discovery.scheduler import DiscoveryScheduler
from arp.discovery.site_finder import DuckDuckGoSearchClient
from arp.engagement.orchestrator import decide_next_action
from arp.engagement.reporting_agent import compile_report
from arp.engagement.triggers import ControversySignal, StaticControversySource, run_trigger_screen, scan_for_stalled_issues
from arp.extraction.pipeline import run_extraction
from arp.extraction.schema_builder import draft_schema
from arp.extraction.financials_pipeline import run_financials_extraction
from arp.transition_plan.indicators import load_indicators
from arp.transition_plan.pipeline import run_transition_plan_assessment
from arp.ingestion.edgar import EdgarDocumentSource
from arp.ingestion.local_files import LocalFileDocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.factory import build_llm_client
from arp.research.activity_generator import build_theme, build_theme_industry_anchored
from arp.research.indirect_exposure.core_sectors import classify_theme_core_sectors
from arp.research.indirect_exposure.criticality import apply_criticality_overlay
from arp.research.indirect_exposure.factory import resolve_indirect_exposure_model
from arp.research.lifecycle_classifier import classify_theme_lifecycle_stages
from arp.research.pipeline import load_theme_run_matches, rank_theme_matches, resume_theme_run, run_thematic_universe
from arp.research.results_diff import diff_theme_results
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
from arp.research.rd_exposure.resolver import RDResolverContext
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
from arp.schemas.engagement import CorrespondenceEntry, EscalationStage, IssueSeverity, TriggerSource
from arp.schemas.portfolio import AggregationResult, AnalyticSpec, PivotSpec, SecurityRef
from arp.schemas.taxonomy import DerivationMethod, TaxonomyRef
from arp.schemas.thematic import ThemeDefinition
from arp.storage.document_store import DocumentContentStore
from arp.storage.engagement_store import EngagementStore
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore
from arp.universe import load_company_universe
from arp.voting.ballot_casting import ManualInstructionBallotPlatform
from arp.voting.pipeline import cast_approved_votes, get_ballots, get_cast_votes, run_voting

app = typer.Typer(help="Agentic Research Pipeline CLI -- the headless path for 1000s-of-companies batch runs.")
theme_app = typer.Typer(help="Thematic investment universe screening.")
taxonomy_app = typer.Typer(help="The reusable, versioned taxonomy library.")
extract_app = typer.Typer(help="Schema-driven data-point extraction.")
transition_plan_app = typer.Typer(help="Transition Plan Assessment: the 64-indicator RAG walk/talk disclosure assessment (Colesanti Senni et al. 2024).")
discover_app = typer.Typer(help="Document discovery: find and download company disclosures.")
runs_app = typer.Typer(help="Inspect and export runs.")
universe_app = typer.Typer(help="Build reusable company universes.")
revenue_catalogue_app = typer.Typer(help="Structured revenue/capex data catalogue mapping.")
engagement_app = typer.Typer(help="Stewardship engagement: record store, triggers, and the escalation-lever checkpoint.")
voting_app = typer.Typer(help="Proxy voting: proposal analysis, policy application, review, and ballot casting.")
portfolio_app = typer.Typer(help="Portfolio holdings aggregation, analytics, and NL Q&A.")
climate_app = typer.Typer(help="Portfolio climate analytics: WACI, financed emissions, coverage.")
documents_app = typer.Typer(help="Operator surface for the document content cache (arp/storage/document_store.py).")
identity_app = typer.Typer(help="Agentic company identity resolution: resolve bare company names to website/CIK before discovery.")
app.add_typer(theme_app, name="theme")
app.add_typer(taxonomy_app, name="taxonomy")
app.add_typer(extract_app, name="extract")
app.add_typer(transition_plan_app, name="transition-plan")
app.add_typer(discover_app, name="discover")
app.add_typer(runs_app, name="runs")
app.add_typer(universe_app, name="universe")
app.add_typer(revenue_catalogue_app, name="revenue-catalogue")
app.add_typer(engagement_app, name="engagement")
app.add_typer(voting_app, name="voting")
app.add_typer(portfolio_app, name="portfolio")
app.add_typer(climate_app, name="climate")
app.add_typer(documents_app, name="documents")
app.add_typer(identity_app, name="identity")


def _engagement_store() -> EngagementStore:
    return EngagementStore(get_settings().engagements_dir)


def _ballot_platform() -> ManualInstructionBallotPlatform:
    return ManualInstructionBallotPlatform(get_settings().ballots_dir)


def _document_content_store() -> DocumentContentStore:
    settings = get_settings()
    return DocumentContentStore(settings.document_store_dir, enabled=settings.document_cache_enabled)


def _registry() -> DocumentSourceRegistry:
    settings = get_settings()
    return DocumentSourceRegistry(
        [
            LocalFileDocumentSource(
                settings.documents_dir,
                content_store=_document_content_store(),
                max_concurrent_parses=settings.max_concurrent_parses,
            ),
            EdgarDocumentSource(
                settings.edgar_user_agent,
                settings.cache_dir,
                content_store=_document_content_store(),
                submissions_ttl_hours=settings.edgar_submissions_ttl_hours,
            ),
        ]
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
        False, help="Use the bundled illustrative ICIO-shaped sample dataset instead of the configured ICIO paths."
    ),
    use_sample_exiobase: bool = typer.Option(
        False, help="Use the bundled illustrative EXIOBASE-shaped sample dataset instead of the configured EXIOBASE paths."
    ),
) -> None:
    """Populates each activity's core_isic_codes -- one classification call
    per activity against the input-output model's fixed industry list, run
    once per theme (not per company) before enabling the indirect-exposure
    tier in `theme run --use-sample-icio`/`--use-sample-exiobase` or a
    configured ARP_ICIO_*/ARP_EXIOBASE_* path. Also applies the bundled
    criticality overlay (arp.research.indirect_exposure.criticality),
    flagging any activity whose freshly-classified core_isic_codes touch a
    USGS/IEA-listed critical mineral's industry.
    """
    settings = get_settings()
    llm = build_llm_client(settings)
    theme = ThemeDefinition.model_validate_json(theme_file.read_text())
    try:
        model = resolve_indirect_exposure_model(settings, use_sample_icio=use_sample_icio, use_sample_exiobase=use_sample_exiobase)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if model is None:
        typer.echo(
            "No input-output data available: set ARP_ICIO_MATRIX_PATH/ARP_ICIO_INDUSTRIES_PATH or "
            "ARP_EXIOBASE_FLOWS_PATH/ARP_EXIOBASE_INDUSTRIES_PATH, or pass --use-sample-icio/--use-sample-exiobase.",
            err=True,
        )
        raise typer.Exit(1)
    updated_theme, _usage = asyncio.run(classify_theme_core_sectors(theme, model, llm))
    updated_theme = apply_criticality_overlay(updated_theme)
    out.write_text(updated_theme.model_dump_json(indent=2))
    classified = sum(1 for a in updated_theme.activities if a.core_isic_codes)
    critical = sum(1 for a in updated_theme.activities if a.criticality_flag)
    typer.echo(
        f"Classified core sectors for {classified}/{len(updated_theme.activities)} activities "
        f"({critical} flagged critical-input). Wrote {out}"
    )


@theme_app.command("classify-lifecycle")
def theme_classify_lifecycle(
    theme_file: Path = typer.Option(..., "--theme"),
    out: Path = typer.Option(..., help="Where to write the ThemeDefinition JSON with lifecycle_stage populated."),
) -> None:
    """Populates each activity's lifecycle_stage (ideation/innovation/
    commercialization/mature) -- one classification call per activity, run
    once per theme, before a run that enables Method C
    (`theme run --enable-rd-exposure`), which only does anything for
    ideation/innovation-stage activities. Independent of --classify-sectors
    (a different concern -- ISIC industry vs. technology maturity); run
    both if you want both tiers populated.
    """
    settings = get_settings()
    llm = build_llm_client(settings)
    theme = ThemeDefinition.model_validate_json(theme_file.read_text())
    updated_theme, _usage = asyncio.run(classify_theme_lifecycle_stages(theme, llm))
    out.write_text(updated_theme.model_dump_json(indent=2))
    classified = sum(1 for a in updated_theme.activities if a.lifecycle_stage is not None)
    typer.echo(f"Classified lifecycle stage for {classified}/{len(updated_theme.activities)} activities. Wrote {out}")


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
        help="Enable the indirect-exposure tier using the bundled illustrative ICIO-shaped sample dataset (demo only).",
    ),
    use_sample_exiobase: bool = typer.Option(
        False,
        "--use-sample-exiobase",
        help="Enable the indirect-exposure tier using the bundled illustrative EXIOBASE-shaped sample dataset (demo only).",
    ),
    revenue_catalogue: Path = typer.Option(
        None, "--revenue-catalogue", help="A structured revenue/capex catalogue CSV (see `revenue-catalogue suggest-mapping`)."
    ),
    catalogue_mapping: Path = typer.Option(
        None, "--catalogue-mapping", help="The reviewed activity->catalogue-label mapping JSON (required alongside --revenue-catalogue)."
    ),
    enable_rd_exposure: bool = typer.Option(
        False,
        "--enable-rd-exposure",
        help="Enable Method C (R&D-spend-intensity + news-mention scoring) for ideation/innovation-stage activities.",
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
    try:
        indirect_model = resolve_indirect_exposure_model(settings, use_sample_icio=use_sample_icio, use_sample_exiobase=use_sample_exiobase)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
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

    rd_resolver = None
    if enable_rd_exposure:
        rd_resolver = RDResolverContext(
            registry=_registry(), settings=settings, isic_model=indirect_model,
            search_client=DuckDuckGoSearchClient(settings.discovery_user_agent),
        )
        typer.echo("R&D/news exposure resolution enabled (ideation/innovation-stage activities only).")

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
            rd_resolver=rd_resolver,
            universe_path=str(universe),
            use_sample_icio=use_sample_icio,
            use_sample_exiobase=use_sample_exiobase,
            revenue_catalogue_path=str(revenue_catalogue) if revenue_catalogue else None,
            catalogue_mapping=mappings,
            enable_rd_exposure=enable_rd_exposure,
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
        False, help="[industry_anchored] Anchor against the bundled illustrative ICIO-shaped ISIC reference list."
    ),
    use_sample_exiobase: bool = typer.Option(
        False, help="[industry_anchored] Anchor against the bundled illustrative EXIOBASE-shaped ISIC reference list."
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
        try:
            model = resolve_indirect_exposure_model(settings, use_sample_icio=use_sample_icio, use_sample_exiobase=use_sample_exiobase)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        if model is None:
            typer.echo(
                "No input-output data available: set ARP_ICIO_MATRIX_PATH/ARP_ICIO_INDUSTRIES_PATH or "
                "ARP_EXIOBASE_FLOWS_PATH/ARP_EXIOBASE_INDUSTRIES_PATH, or pass --use-sample-icio/--use-sample-exiobase.",
                err=True,
            )
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
    use_sample_exiobase: bool = typer.Option(
        False, help="Classify any activity missing core_isic_codes using the bundled sample EXIOBASE dataset first."
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
    try:
        updated_theme, _usage = asyncio.run(
            map_theme_to_standards(
                taxonomy.theme, settings, llm,
                use_sample_icio=use_sample_icio,
                use_sample_exiobase=use_sample_exiobase,
                use_sample_standards=use_sample_standards,
            )
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
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


@extract_app.command("financials-run")
def extract_financials_run(
    universe: Path = typer.Option(...),
) -> None:
    """Extracts each company's disclosed business segments (name,
    description, revenue, income, assets), total CapEx, and total R&D
    expense -- each with a grounded description/breakdown where disclosed
    -- in a single combined evidence-gathering + extractor/verifier pass per
    company (these are almost always wanted together, so this fetches each
    company's documents once and makes one LLM call pair instead of three),
    with the same independent-verifier + programmatic-grounding precision
    controls as `extract run`."""
    settings = get_settings()
    llm = build_llm_client(settings)
    companies = load_company_universe(universe)
    typer.echo(f"Extracting segments/CapEx/R&D across {len(companies)} companies...")
    run_id = asyncio.run(
        run_financials_extraction(companies, llm=llm, registry=_registry(), settings=settings, run_store=_run_store())
    )
    typer.echo(f"Run complete: {run_id} (see runs/{run_id}/)")


@transition_plan_app.command("indicators")
def transition_plan_indicators(out: Path = typer.Option(None, help="Write the 64 indicators as JSON here; omit to print a summary.")) -> None:
    indicators = load_indicators()
    if out:
        out.write_text(json.dumps([i.model_dump(mode="json") for i in indicators], indent=2))
        typer.echo(f"Wrote {len(indicators)} indicators to {out}")
        return
    for i in indicators:
        typer.echo(f"{i.number:>2}. [{i.category.value}/{i.walk_or_talk.value}] {i.question}")


@transition_plan_app.command("run")
def transition_plan_run(
    universe: Path = typer.Option(...),
) -> None:
    """Assesses each company's climate transition disclosures against the
    64 indicators from Colesanti Senni et al. (2024) -- target-setting
    ("talk") vs. concrete implementation ("walk") -- via one grounded RAG
    verdict per indicator, with the same programmatic citation-grounding
    check as `extract run`."""
    settings = get_settings()
    llm = build_llm_client(settings)
    companies = load_company_universe(universe)
    typer.echo(f"Assessing transition plans across {len(companies)} companies against 64 indicators...")
    run_id = asyncio.run(
        run_transition_plan_assessment(companies, llm=llm, registry=_registry(), settings=settings, run_store=_run_store())
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


@documents_app.command("warm")
def documents_warm(
    universe: Path = typer.Option(..., help="Company universe JSON to warm the document cache for."),
    doc_types: str = typer.Option("", help="Comma-separated DocType values; empty = all supported types."),
    concurrency: int = typer.Option(4, help="Max companies fetched/parsed concurrently."),
) -> None:
    """Pays the fetch/parse cost for every company in a universe up
    front -- off-peak, before a batch run -- and surfaces any file that
    fails to parse now instead of mid-run. Safe to re-run: everything it
    touches is content-addressed, so an already-warm document is a fast
    cache hit rather than repeated work."""
    settings = get_settings()
    companies = load_company_universe(universe)
    types = [DocType(t.strip()) for t in doc_types.split(",") if t.strip()] or None
    registry = _registry()
    sem = asyncio.Semaphore(concurrency)
    failures: list[str] = []

    async def _warm_one(company: CompanyRef) -> int:
        async with sem:
            try:
                docs = await registry.fetch_all(company, types)
            except Exception as exc:  # noqa: BLE001 - isolate one company's failure from the rest
                failures.append(f"{company.company_id}: {exc}")
                return 0
        return len(docs)

    async def _run() -> list[int]:
        return await asyncio.gather(*(_warm_one(c) for c in companies))

    typer.echo(f"Warming document cache for {len(companies)} companies...")
    counts = asyncio.run(_run())
    typer.echo(f"Warmed {sum(counts)} documents across {len(companies)} companies.")
    if failures:
        typer.echo(f"{len(failures)} companies had errors:", err=True)
        for f in failures:
            typer.echo(f"  {f}", err=True)


@documents_app.command("cache-stats")
def documents_cache_stats() -> None:
    from arp.ingestion.edgar import _edgar_parser_version
    from arp.ingestion.local_files import parser_version

    stats = _document_content_store().stats()
    stats["current_local_parser_version"] = parser_version()
    stats["current_edgar_parser_version"] = _edgar_parser_version()
    typer.echo(json.dumps(stats, indent=2))


@documents_app.command("cache-prune")
def documents_cache_prune(yes: bool = typer.Option(False, "--yes", help="Skip the confirmation prompt.")) -> None:
    """Deletes parsed_content rows stamped with a parser_version other
    than whatever's currently active (local file parsing and EDGAR
    extraction each have their own) and reclaims the freed space. Do not
    run this against a live API process -- VACUUM needs exclusive access
    to the database file."""
    from arp.ingestion.edgar import _edgar_parser_version
    from arp.ingestion.local_files import parser_version

    if not yes:
        typer.confirm(
            "This runs VACUUM and requires exclusive access to the document store -- "
            "make sure the API server is stopped. Continue?",
            abort=True,
        )
    current = [parser_version(), _edgar_parser_version()]
    deleted = _document_content_store().prune(keep_parser_version=current)
    typer.echo(f"Pruned {deleted} stale parsed_content row(s). Kept: {current}")


@identity_app.command("resolve")
def identity_resolve(
    names_file: Path = typer.Option(
        ..., "--names-file", help="CSV/JSON of company names (same shape arp.universe.load_company_universe reads; website/cik not required)."
    ),
) -> None:
    """Resolves each company's real-world identity (website/CIK) via the
    propose -> resolve -> challenge -> adjudicate graph -- a separate,
    one-time-per-company enrichment run, not part of document discovery
    itself. Anything ambiguous is queued for review (`arp identity
    review-queue` / `arp identity review`) instead of guessed. Once
    resolved, export a usable universe with `arp identity
    enriched-universe` and feed it into `arp discover run --universe`.
    """
    settings = get_settings()
    companies = load_company_universe(names_file)
    llm = build_llm_client(settings)
    run_store = _run_store()
    typer.echo(f"Resolving identity for {len(companies)} companies...")
    run_id = asyncio.run(run_identity_resolution(companies, llm=llm, settings=settings, run_store=run_store))
    manifest = run_store.load_manifest(run_id)
    typer.echo(f"Run complete: {run_id} ({manifest.review_count}/{len(companies)} flagged for review)")


@identity_app.command("review-queue")
def identity_review_queue(run_id: str) -> None:
    run_store = _run_store()
    from arp.orchestration.review_queue import latest_decisions

    rows = run_store.read_jsonl(run_store.review_queue_path(run_id))
    decisions = latest_decisions(run_store, run_id)
    pending = [r for r in rows if r["item_key"] not in decisions]
    if not pending:
        typer.echo("Nothing pending review.")
        return
    for r in pending:
        typer.echo(f"{r['item_key']}: {r['input_name']!r} -> verdict={r['verdict']} confidence={r['confidence']:.2f}")
        typer.echo(f"  rationale: {r['rationale']}")


@identity_app.command("review")
def identity_review(
    run_id: str,
    item_key: str = typer.Argument(..., help="The company_id, as shown by `arp identity review-queue`."),
    decision: str = typer.Option(..., help="approve | edit | reject"),
    by: str = typer.Option(...),
    website: str = typer.Option(None, help="Corrected website. With --decision edit, at least one of --website/--cik is required."),
    cik: str = typer.Option(None, help="Corrected CIK."),
    comment: str = typer.Option(None),
) -> None:
    from arp.orchestration.review_queue import record_review_decision

    if decision not in ("approve", "edit", "reject"):
        typer.echo("decision must be approve, edit, or reject", err=True)
        raise typer.Exit(1)
    if decision == "edit" and not (website or cik):
        typer.echo("--website and/or --cik is required with --decision edit", err=True)
        raise typer.Exit(1)
    edited_value = {"resolved_website": website, "resolved_cik": cik} if decision == "edit" else None
    record_review_decision(_run_store(), run_id, item_key, decision, by, edited_value, comment)
    typer.echo("Recorded.")


@identity_app.command("enriched-universe")
def identity_enriched_universe(
    run_id: str, out: Path = typer.Option(..., help="Where to write the enriched universe JSON.")
) -> None:
    """Writes a normal company universe (website/cik filled in for every
    resolved-and-clean or reviewer-approved company), directly usable as
    `arp discover run --universe <out>`."""
    run_store = _run_store()
    companies = enriched_universe(run_store, run_id)
    out.write_text(json.dumps([c.model_dump(mode="json") for c in companies], indent=2))
    typer.echo(f"Wrote {len(companies)} resolved companies to {out}")


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


@runs_app.command("results")
def runs_results(run_id: str) -> None:
    """Every CompanyMatch for a theme run, ranked by
    arbitration.composite_score descending (Step 5's ranked-list output)."""
    matches = load_theme_run_matches(_run_store(), run_id)
    if matches is None:
        typer.echo("Run not found or not a theme run", err=True)
        raise typer.Exit(1)
    ranked = rank_theme_matches(matches)
    typer.echo(json.dumps([m.model_dump(mode="json") for m in ranked], indent=2))


@runs_app.command("diff")
def runs_diff(run_id_a: str, run_id_b: str) -> None:
    """Deterministic diff between two theme runs' results (added/dropped/
    verdict-changed/confidence-changed company x activity pairs) -- no LLM
    call, the join key ('{company_id}:{activity_id}') is exact."""
    store = _run_store()
    matches_a = load_theme_run_matches(store, run_id_a)
    if matches_a is None:
        typer.echo(f"Run not found or not a theme run: {run_id_a}", err=True)
        raise typer.Exit(1)
    matches_b = load_theme_run_matches(store, run_id_b)
    if matches_b is None:
        typer.echo(f"Run not found or not a theme run: {run_id_b}", err=True)
        raise typer.Exit(1)
    diff = diff_theme_results(run_id_a, run_id_b, matches_a, matches_b)
    typer.echo(json.dumps(diff.model_dump(mode="json"), indent=2))


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


@engagement_app.command("record-list")
def engagement_record_list() -> None:
    for r in _engagement_store().list_all():
        open_issues = sum(1 for i in r.issues if i.status.value == "open")
        typer.echo(f"{r.company_id}\t{r.name}\t{len(r.issues)} issue(s), {open_issues} open")


@engagement_app.command("record-show")
def engagement_record_show(company_id: str) -> None:
    record = _engagement_store().get(company_id)
    if record is None:
        typer.echo("Not found", err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps(record.model_dump(mode="json"), indent=2))


@engagement_app.command("issue-open")
def engagement_issue_open(
    company_id: str,
    name: str,
    theme: str = typer.Option(...),
    severity: IssueSeverity = typer.Option(IssueSeverity.MEDIUM),
) -> None:
    _record, issue = _engagement_store().open_issue(company_id, name, theme=theme, severity=severity, source=TriggerSource.ANALYST_RAISED)
    typer.echo(f"Opened issue {issue.issue_id} ({theme}) for {company_id}")


@engagement_app.command("issue-next-action")
def engagement_issue_next_action(company_id: str, issue_id: str) -> None:
    settings = get_settings()
    store = _engagement_store()
    record = store.get(company_id)
    if record is None:
        typer.echo("Record not found", err=True)
        raise typer.Exit(1)
    issue = next((i for i in record.issues if i.issue_id == issue_id), None)
    if issue is None:
        typer.echo("Issue not found", err=True)
        raise typer.Exit(1)
    decision = decide_next_action(issue, settings.engagement_sla_days)
    typer.echo(f"{decision.action.value}: {decision.reason}")


@engagement_app.command("issue-escalate")
def engagement_issue_escalate(
    company_id: str,
    issue_id: str,
    stage: EscalationStage = typer.Option(..., help="The next escalation-ladder step."),
    by: str = typer.Option(..., help="Who made this escalation-lever decision -- the non-negotiable human checkpoint."),
    reason: str = typer.Option(""),
) -> None:
    _engagement_store().set_escalation_stage(company_id, issue_id, stage, by, reason)
    typer.echo(f"Escalated {company_id}/{issue_id} to {stage.value} (by {by})")


@engagement_app.command("log-correspondence")
def engagement_log_correspondence(
    company_id: str,
    issue_id: str,
    type: str = typer.Option(..., help="letter | call | meeting | email | other"),
    summary: str = typer.Option(...),
    logged_by: str = typer.Option(None),
) -> None:
    _engagement_store().add_correspondence(company_id, issue_id, CorrespondenceEntry(type=type, summary=summary, logged_by=logged_by))
    typer.echo("Logged.")


@engagement_app.command("verify-commitment")
def engagement_verify_commitment(company_id: str, issue_id: str, commitment_id: str, by: str = typer.Option(...)) -> None:
    from arp.engagement.tracking_agent import log_commitment_verified

    log_commitment_verified(_engagement_store(), company_id, issue_id, commitment_id, by)
    typer.echo("Verified.")


@engagement_app.command("dossier-draft")
def engagement_dossier_draft(
    company_id: str,
    issue_id: str,
    universe: Path = typer.Option(..., help="Universe CSV/JSON containing this company (for name/ticker/cik/website)."),
    out: Path = typer.Option(..., help="Where to write the ResearchDossier JSON."),
) -> None:
    """Research Agent: drafts a grounded briefing dossier for one issue.
    The result is written to disk, not auto-applied, so a human can run the
    dossier-accuracy review checkpoint before any Drafting Agent handoff."""
    from arp.engagement.research_agent import research_company_issue

    settings = get_settings()
    llm = build_llm_client(settings)
    store = _engagement_store()
    record = store.get(company_id)
    if record is None:
        typer.echo("Engagement record not found -- open an issue first with `arp engagement issue-open`.", err=True)
        raise typer.Exit(1)
    issue = next((i for i in record.issues if i.issue_id == issue_id), None)
    if issue is None:
        typer.echo("Issue not found", err=True)
        raise typer.Exit(1)
    company = next((c for c in load_company_universe(universe) if c.company_id == company_id), None)
    if company is None:
        typer.echo(f"{company_id} not found in {universe}", err=True)
        raise typer.Exit(1)
    dossier, needs_review, _usage = asyncio.run(
        research_company_issue(
            company, issue, record, registry=_registry(), llm=llm,
            fuzzy_threshold=settings.grounding_fuzzy_threshold, confidence_review_threshold=settings.confidence_review_threshold,
        )
    )
    out.write_text(dossier.model_dump_json(indent=2))
    typer.echo(f"Wrote dossier to {out} (needs_review={needs_review})")


@engagement_app.command("trigger-scan")
def engagement_trigger_scan(
    universe: Path = typer.Option(...),
    signals: Path = typer.Option(None, help="JSON list of {company_id, theme, severity, detail} controversy signals."),
) -> None:
    """Runs the trigger & detection layer: opens a new issue for every
    controversy signal without an already-open issue on the same theme,
    plus an SLA sweep flagging stalled issues."""
    companies = load_company_universe(universe)
    store = _engagement_store()
    signal_list = [ControversySignal(**s) for s in json.loads(signals.read_text())] if signals else []
    source = StaticControversySource(signal_list)
    events = asyncio.run(run_trigger_screen(companies, source, store))
    events += scan_for_stalled_issues(store, get_settings().engagement_sla_days)
    for e in events:
        typer.echo(f"{e.source.value}\t{e.company_id}\t{e.theme}\t{e.severity.value}\tissue={e.raised_issue_id}")
    typer.echo(f"{len(events)} trigger event(s).")


@engagement_app.command("report")
def engagement_report(period_label: str = typer.Option(...), run_id: str = typer.Option(None, help="Include a voting run's cast votes.")) -> None:
    vote_records = []
    if run_id:
        run_store = RunStore(get_settings().runs_dir)
        for ballot in get_ballots(run_store, run_id):
            vote_records.extend(ballot.votes)
        cast_by_id = {v.vote_record_id: v for v in get_cast_votes(run_store, run_id)}
        vote_records = [cast_by_id.get(v.vote_record_id, v) for v in vote_records]
    report = compile_report(_engagement_store().list_all(), vote_records, period_label)
    typer.echo(json.dumps(report.model_dump(mode="json"), indent=2))


@voting_app.command("run")
def voting_run(
    universe: Path = typer.Option(...),
    meeting_dates: Path = typer.Option(None, help="Optional JSON object mapping company_id -> meeting_date."),
) -> None:
    settings = get_settings()
    llm = build_llm_client(settings)
    companies = load_company_universe(universe)
    dates = json.loads(meeting_dates.read_text()) if meeting_dates else {}
    typer.echo(f"Running proxy voting analysis across {len(companies)} companies...")
    run_id = asyncio.run(
        run_voting(
            companies, llm=llm, registry=_registry(), engagement_store=_engagement_store(),
            settings=settings, run_store=_run_store(), meeting_dates=dates, fund_name=settings.fund_name,
        )
    )
    typer.echo(f"Run complete: {run_id} (see runs/{run_id}/). Every proposal is queued for review -- use `arp voting review`.")


@voting_app.command("ballots")
def voting_ballots(run_id: str) -> None:
    for ballot in get_ballots(_run_store(), run_id):
        typer.echo(f"{ballot.company_id}\t{ballot.name}\t{len(ballot.votes)} proposal(s)")
        for v in ballot.votes:
            rec = v.policy_recommendation
            flag = " [ALIGNMENT FLAG]" if rec and rec.engagement_alignment_flag else ""
            typer.echo(f"  #{v.proposal.proposal_number} ({v.proposal.type.value}): recommend {rec.vote.value if rec else '?'}{flag}")


@voting_app.command("review")
def voting_review(
    run_id: str,
    item_key: str = typer.Argument(..., help="'{company_id}:{proposal_number}', as shown by `arp voting ballots`."),
    decision: str = typer.Option(..., help="approve | edit | reject"),
    by: str = typer.Option(...),
    vote: str = typer.Option(None, help="Required if --decision edit: for | against | abstain | withhold."),
    co_signed_by: str = typer.Option(None, help="Required before casting when the item carries an engagement alignment flag."),
    comment: str = typer.Option(None),
) -> None:
    from arp.orchestration.review_queue import record_review_decision

    if decision not in ("approve", "edit", "reject"):
        typer.echo("decision must be approve, edit, or reject", err=True)
        raise typer.Exit(1)
    if decision == "edit" and not vote:
        typer.echo("--vote is required with --decision edit", err=True)
        raise typer.Exit(1)
    edited_value = {"vote": vote, "co_signed_by": co_signed_by} if decision == "edit" else ({"co_signed_by": co_signed_by} if co_signed_by else None)
    record_review_decision(_run_store(), run_id, item_key, decision, by, edited_value, comment)
    typer.echo("Recorded.")


@voting_app.command("cast")
def voting_cast(run_id: str) -> None:
    """Ballot Casting Agent: casts every reviewed-and-approved vote not
    already cast. Never casts an item with no recorded human decision, and
    refuses an engagement-alignment-flagged item with no co-sign."""
    cast = asyncio.run(cast_approved_votes(run_id, _run_store(), _ballot_platform()))
    typer.echo(f"Cast {len(cast)} vote(s).")
    for v in cast:
        typer.echo(f"  {v.proposal.company_id} #{v.proposal.proposal_number}: {v.human_decision.vote.value} ({v.cast_confirmation.confirmation_id})")
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


@portfolio_app.command("pivot")
def portfolio_pivot(
    row_dim: str = typer.Option(..., help="portfolio_id | asset_class | company_id | company_name | sector | country | currency"),
    col_dim: str = typer.Option(..., help="Same choices as --row-dim."),
    metric: str = typer.Option("market_value_sum", help="market_value_sum | weighted_avg_datapoint | count"),
    portfolio: list[str] = typer.Option(None, "--portfolio", help="Restrict to these portfolio_ids; repeatable."),
    company_id: str = typer.Option(None, help="Filter to one issuer, e.g. bmw."),
    asset_class: str = typer.Option(None),
    data_point_field_id: str = typer.Option(None, help="Required for metric=weighted_avg_datapoint, e.g. climate_carbon_intensity."),
    as_of: str = typer.Option(None, help="Snapshot date; defaults to the latest available."),
    name: str = typer.Option("cli pivot"),
) -> None:
    """A two-dimension permutation of `arp portfolio aggregate` -- e.g.
    --row-dim sector --col-dim asset_class to see the whole exposure
    breakdown as a single cross-tab instead of one dimension at a time."""
    store = _portfolio_store()
    security_filter: dict[str, str] = {}
    if company_id:
        security_filter["company_id"] = company_id
    if asset_class:
        security_filter["asset_class"] = asset_class
    spec = PivotSpec(
        name=name, portfolio_filter=portfolio or [], security_filter=security_filter, row_dim=row_dim, col_dim=col_dim,
        metric=metric, data_point_field_id=data_point_field_id, as_of=as_of,
    )
    securities, companies = _portfolio_directories(store)
    try:
        result = analytics.execute_pivot(spec, store, securities, companies)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps(result.model_dump(mode="json"), indent=2))


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
