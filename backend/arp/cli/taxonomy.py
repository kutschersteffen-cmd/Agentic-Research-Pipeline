from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.cli._shared import _registry, _resolve_taxonomy_ref_or_exit, _run_store, _taxonomy_store
from arp.cli.taxonomy_infer import infer_app
from arp.config import get_settings
from arp.discovery.site_finder import build_web_search_client
from arp.llm.factory import build_llm_client
from arp.research.activity_generator import build_theme, build_theme_industry_anchored
from arp.research.authority_taxonomy import run as authority_run
from arp.research.indirect_exposure.factory import NO_MODEL, resolve_indirect_exposure_model
from arp.research.standards_mapping.mapper import format_standards_csv, map_theme_to_standards
from arp.research.stock_inference import RETIRED, retired_message
from arp.research.taxonomy_sources.authority import build_theme_from_authority_sources
from arp.research.taxonomy_sources.compare import compare_taxonomies, merge_taxonomies
from arp.research.taxonomy_sources.discovery import discover_authority_sources, discover_thematic_funds
from arp.research.taxonomy_sources.news_mining import build_theme_from_news_and_transcripts
from arp.schemas.taxonomy import DerivationMethod
from arp.schemas.thematic import ThemeDefinition
from arp.universe import load_company_universe

taxonomy_app = typer.Typer(help="The reusable, versioned taxonomy library.")
author_app = typer.Typer(help="Author a taxonomy from authority sources, stage by stage.")
taxonomy_app.add_typer(author_app, name="author")
taxonomy_app.add_typer(infer_app, name="infer")


def _author(fn):
    """Runs an authoring step; engine errors become a stderr message and exit 1."""
    try:
        return fn()
    except (authority_run.WrongStage, ValueError, KeyError, OSError) as e:
        typer.echo(e.args[0] if isinstance(e, KeyError) and e.args else str(e), err=True)
        raise typer.Exit(1) from None


@author_app.command("start")
def author_start(
    name: str,
    scope: str = typer.Option(..., help="What the theme covers."),
    theme_key: str = typer.Option(None),
    guidance: str = typer.Option(""),
    value_chain: bool = typer.Option(False, "--value-chain"),
) -> None:
    settings = get_settings()
    state = _author(lambda: asyncio.run(authority_run.start_run(
        name, theme_key, scope, guidance, value_chain, run_store=_run_store(),
        search_client=build_web_search_client(settings.discovery_user_agent),
        llm=build_llm_client(settings), user_agent=settings.discovery_user_agent,
    )))
    typer.echo(f"run: {state.run_id}")
    for c in state.candidates:
        typer.echo(f"{c.url}\tfetchable={c.fetchable}\t{c.summary}")
    typer.echo(f"stage: {state.stage}")


@author_app.command("select")
def author_select(
    run_id: str,
    url: list[str] = typer.Option([], "--url"),
    file: list[Path] = typer.Option([], "--file"),  # local operator: paths are not confined
) -> None:
    settings = get_settings()
    store = _run_store()

    def go():
        model = resolve_indirect_exposure_model(settings) if authority_run.load_state(run_id, store).value_chain else None
        return asyncio.run(authority_run.select_sources(
            run_id, url, file, run_store=store, llm=build_llm_client(settings), settings=settings,
            user_agent=settings.discovery_user_agent, value_chain_model=model,
        ))

    state = _author(go)
    typer.echo(state.notes)
    typer.echo(f"stage: {state.stage}")


@author_app.command("review")
def author_review(run_id: str, edit: Path = typer.Option(None, help="A draft JSON file to save as the draft.")) -> None:
    store = _run_store()

    def go():
        if edit is not None:
            return authority_run.put_draft(run_id, ThemeDefinition.model_validate_json(edit.read_text()), store)
        return authority_run.load_state(run_id, store)

    state = _author(go)
    typer.echo(json.dumps(state.draft.model_dump(mode="json") if state.draft else None, indent=2))
    typer.echo(f"stage: {state.stage}")


@author_app.command("accept")
def author_accept(run_id: str) -> None:
    state = _author(lambda: authority_run.accept(run_id, _run_store(), _taxonomy_store()))
    typer.echo(state.taxonomy_id)
    typer.echo(f"stage: {state.stage}")


@taxonomy_app.command("discover-sources")
def taxonomy_discover_sources(
    name: str,
    out: Path = typer.Option(None, help="Optional: write the discovered candidates as JSON instead of printing them."),
) -> None:
    """Web-searches for candidate authority sources (official taxonomies,
    standards bodies) and existing thematic ETFs/indices for this theme --
    the research step, so you can review and pick real sources before
    running a derivation with --method authority_source."""
    settings = get_settings()
    search_client = build_web_search_client(settings.discovery_user_agent)

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



@taxonomy_app.command("create")
def taxonomy_create(
    name: str,
    description: str = "",
    method: DerivationMethod = typer.Option(DerivationMethod.LLM_DRAFT, "--method", help="How to derive this taxonomy."),
    use_sample_io: bool = typer.Option(
        False, "--use-sample-io", help="[industry_anchored] Anchor against the bundled sample input-output industry list."
    ),
    authority_url: list[str] = typer.Option(
        [], "--authority-url", help="[authority_source] One or more source URLs (repeatable). See `taxonomy discover-sources`."
    ),
    universe: Path = typer.Option(
        None, help="[news_transcript_mining] A sample company universe CSV/JSON."
    ),
) -> None:
    """Drafts and saves a new taxonomy (v1) -- a reusable, versioned
    artifact, unlike `theme decompose`'s throwaway JSON file. Pick a
    derivation --method; each has its own required inputs (see the option
    help above)."""
    if method in RETIRED:
        typer.echo(retired_message(method), err=True)
        raise typer.Exit(1)
    settings = get_settings()
    llm = build_llm_client(settings)

    if method == DerivationMethod.LLM_DRAFT:
        theme, _usage = asyncio.run(build_theme(name, description, llm))
        notes = "Freeform LLM draft, no industry anchor."

    elif method == DerivationMethod.INDUSTRY_ANCHORED:
        try:
            model = resolve_indirect_exposure_model(settings, use_sample=use_sample_io)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        if model is None:
            typer.echo(f"{NO_MODEL}, or pass --use-sample-io.", err=True)
            raise typer.Exit(1)
        theme, _usage = asyncio.run(build_theme_industry_anchored(name, description, model.industry_reference_list(), llm))
        notes = f"Anchored against {model.edition_label} ({len(model.industry_reference_list())} industries)."

    elif method == DerivationMethod.AUTHORITY_SOURCE:
        if not authority_url:
            typer.echo("Provide at least one --authority-url (see `arp taxonomy discover-sources`).", err=True)
            raise typer.Exit(1)
        theme, notes, _usage = asyncio.run(
            build_theme_from_authority_sources(name, description, authority_url, llm, settings.discovery_user_agent)
        )

    elif method == DerivationMethod.NEWS_TRANSCRIPT_MINING:
        companies = load_company_universe(universe) if universe else None
        search_client = build_web_search_client(settings.discovery_user_agent)
        theme, notes, _usage = asyncio.run(
            build_theme_from_news_and_transcripts(
                name, description, llm, search_client=search_client, companies=companies,
                registry=_registry() if companies else None,
            )
        )

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
    use_sample_io: bool = typer.Option(
        False, "--use-sample-io", help="Classify any activity missing core_isic_codes using the bundled sample input-output model first."
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
                use_sample_io=use_sample_io,
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
