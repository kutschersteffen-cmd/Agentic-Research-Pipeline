from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.cli._shared import _registry, _resolve_taxonomy_ref_or_exit, _taxonomy_store
from arp.config import get_settings
from arp.discovery.site_finder import DuckDuckGoSearchClient
from arp.llm.factory import build_llm_client
from arp.research.activity_generator import build_theme, build_theme_industry_anchored
from arp.research.indirect_exposure.factory import resolve_indirect_exposure_model
from arp.research.standards_mapping.mapper import format_standards_csv, map_theme_to_standards
from arp.research.taxonomy_sources.authority import build_theme_from_authority_sources
from arp.research.taxonomy_sources.compare import compare_taxonomies, merge_taxonomies
from arp.research.taxonomy_sources.discovery import discover_authority_sources, discover_thematic_funds
from arp.research.taxonomy_sources.empirical import build_theme_empirical
from arp.research.taxonomy_sources.etf_holdings import build_theme_from_holdings
from arp.research.taxonomy_sources.news_mining import build_theme_from_news_and_transcripts
from arp.schemas.taxonomy import DerivationMethod
from arp.schemas.thematic import ThemeDefinition
from arp.universe import load_company_universe

taxonomy_app = typer.Typer(help="The reusable, versioned taxonomy library.")


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
