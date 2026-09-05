from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.cli._shared import _registry, _run_store, _taxonomy_store
from arp.config import get_settings
from arp.discovery.site_finder import DuckDuckGoSearchClient
from arp.llm.factory import build_llm_client, build_verifier_llm_client
from arp.research.activity_generator import build_theme
from arp.research.indirect_exposure.core_sectors import classify_theme_core_sectors
from arp.research.indirect_exposure.criticality import apply_criticality_overlay
from arp.research.indirect_exposure.factory import resolve_indirect_exposure_model
from arp.research.lifecycle_classifier import classify_theme_lifecycle_stages
from arp.research.pipeline import resume_theme_run, run_thematic_universe
from arp.research.rd_exposure.resolver import RDResolverContext
from arp.research.revenue_exposure.catalogue import by_company as catalogue_by_company
from arp.research.revenue_exposure.catalogue import load_catalogue
from arp.research.revenue_exposure.resolver import RevenueResolverContext
from arp.schemas.revenue_exposure import ActivityCatalogueMapping
from arp.schemas.thematic import ThemeDefinition
from arp.universe import load_company_universe

theme_app = typer.Typer(help="Thematic investment universe screening.")


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
    verifier_llm = build_verifier_llm_client(settings)
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
            verifier_llm=verifier_llm,
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
    verifier_llm = build_verifier_llm_client(settings)
    try:
        run_id = asyncio.run(
            resume_theme_run(
                run_id, llm=llm, verifier_llm=verifier_llm, registry=_registry(), settings=settings, run_store=_run_store()
            )
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Resumed run complete: {run_id} (see runs/{run_id}/)")
