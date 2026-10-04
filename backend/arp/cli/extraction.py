from __future__ import annotations

import asyncio
import re
from pathlib import Path

import typer

from arp.checks.effectiveness import effectiveness
from arp.cli._shared import _and_drain, _registry, _run_store, _xbrl_source
from arp.config import get_settings
from arp.extraction.financials_pipeline import run_financials_extraction
from arp.extraction.pipeline import run_extraction
from arp.extraction.schema_builder import draft_schema
from arp.extraction.tnfd_pipeline import run_tnfd_extraction
from arp.llm.factory import build_llm_client, build_verifier_llm_client
from arp.orchestration.jobs import NotResumable, RunBusy, resume_run
from arp.presets.registry import PRESETS, install_preset
from arp.review.analytics import MONTH_PATTERN, monthly_totals
from arp.schemas.datapoints import DataPointSchema
from arp.storage.schema_registry import SchemaRegistry
from arp.universe import load_company_universe

extract_app = typer.Typer(help="Schema-driven data-point extraction.")


@extract_app.command("draft-schema")
def extract_draft_schema(criteria_text: str, out: Path = typer.Option(...)) -> None:
    settings = get_settings()
    llm = build_llm_client(settings)
    schema, _usage = asyncio.run(draft_schema(criteria_text, llm))
    out.write_text(schema.model_dump_json(indent=2))
    typer.echo(f"Wrote schema with {len(schema.fields)} fields to {out}")



presets_app = typer.Typer(help="Built-in schema presets.")
extract_app.add_typer(presets_app, name="presets")


@presets_app.command("list")
def presets_list() -> None:
    for pid, build in PRESETS.items():
        schema = build()
        typer.echo(f"{pid}\t{schema.name}\t{len(schema.fields)} fields")


@presets_app.command("install")
def presets_install(preset_id: str) -> None:
    try:
        saved = install_preset(preset_id, SchemaRegistry(get_settings().schema_registry_dir))
    except KeyError:
        typer.echo(f"Unknown preset '{preset_id}'.", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"Installed {saved.schema_id} v{saved.version}")


@extract_app.command("run")
def extract_run(
    schema_file: Path = typer.Option(None, "--schema"),
    universe: Path = typer.Option(None),
    trial: bool = typer.Option(False, "--trial", help="Allow draft fields; the run is marked as a trial."),
    run_id: str = typer.Option(None, "--run-id", help="Resume this run (any batch run type) instead of starting one."),
) -> None:
    settings = get_settings()
    if run_id:
        try:
            asyncio.run(_and_drain(resume_run(run_id, settings=settings, run_store=_run_store(), registry=_registry())))
        except (NotResumable, RunBusy) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(f"Run complete: {run_id} (see runs/{run_id}/)")
        return
    if schema_file is None or universe is None:
        typer.echo("Pass --schema and --universe, or --run-id to resume a run.", err=True)
        raise typer.Exit(1)
    llm = build_llm_client(settings)
    verifier_llm = build_verifier_llm_client(settings)
    schema = DataPointSchema.model_validate_json(schema_file.read_text())
    companies = load_company_universe(universe)
    typer.echo(f"Extracting schema '{schema.name}' ({len(schema.fields)} fields) across {len(companies)} companies...")
    run_id = asyncio.run(_and_drain(
        run_extraction(
            schema, companies, llm=llm, verifier_llm=verifier_llm, registry=_registry(), settings=settings, run_store=_run_store(), trial=trial,
            xbrl_source=_xbrl_source() if settings.xbrl_facts_enabled else None,
        )
    ))
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
    verifier_llm = build_verifier_llm_client(settings)
    companies = load_company_universe(universe)
    typer.echo(f"Extracting segments/CapEx/R&D across {len(companies)} companies...")
    run_id = asyncio.run(_and_drain(
        run_financials_extraction(
            companies,
            llm=llm,
            verifier_llm=verifier_llm,
            registry=_registry(),
            settings=settings,
            run_store=_run_store(),
            xbrl_source=_xbrl_source() if settings.xbrl_facts_enabled else None,
        )
    ))
    typer.echo(f"Run complete: {run_id} (see runs/{run_id}/)")



@extract_app.command("tnfd-run")
def extract_tnfd_run(
    universe: Path = typer.Option(...),
    as_of: str = typer.Option(..., help="Reporting period this run covers, e.g. 'FY2025' -- applied to every "
                                         "company in the run. No 'latest' default."),
) -> None:
    """Extracts each company's TNFD (nature-related financial disclosure)
    reporting -- all 4 pillars/14 recommendations, core global metrics,
    sector metrics/LEAP considerations where the company's sector is
    covered, and general requirements -- in a single combined evidence-
    gathering + extractor/verifier pass per company, with the same
    independent-verifier + programmatic-grounding precision controls as
    `extract run`."""
    settings = get_settings()
    llm = build_llm_client(settings)
    verifier_llm = build_verifier_llm_client(settings)
    companies = load_company_universe(universe)
    typer.echo(f"Extracting TNFD disclosures ({as_of}) across {len(companies)} companies...")
    run_id = asyncio.run(_and_drain(
        run_tnfd_extraction(
            companies, as_of, llm=llm, verifier_llm=verifier_llm, registry=_registry(), settings=settings, run_store=_run_store()
        )
    ))
    typer.echo(f"Run complete: {run_id} (see runs/{run_id}/)")


@extract_app.command("check-effectiveness")
def extract_check_effectiveness() -> None:
    """Per check and field version: how often a firing check led a reviewer to correct or reject the value."""
    stats = effectiveness(_run_store())
    typer.echo(f"{'check':<28}{'field':<28}{'ver':>4}{'fired':>7}{'decided':>9}{'hit%':>7}{'overturn%':>11}")
    for s in stats:
        typer.echo(
            f"{s.check_id:<28}{s.field_id:<28}{s.field_version if s.field_version is not None else '-':>4}"
            f"{s.fired:>7}{s.decided:>9}{s.hit_rate:>7.0%}{s.overturn_rate:>11.0%}"
        )


@extract_app.command("review-analytics")
def extract_review_analytics(month: str = typer.Option(..., help="YYYY-MM")) -> None:
    """Reviewer correction reasons in a month, by field, extractor model and document type."""
    if not re.match(MONTH_PATTERN, month):
        raise typer.BadParameter("expected YYYY-MM", param_hint="--month")
    typer.echo(f"{'field':<28}{'model':<26}{'doc type':<22}{'reason':<24}{'count':>6}")
    for t in monthly_totals(_run_store(), month):
        typer.echo(f"{t.field_id:<28}{t.model or '-':<26}{t.doc_type or '-':<22}{t.reason:<24}{t.count:>6}")
