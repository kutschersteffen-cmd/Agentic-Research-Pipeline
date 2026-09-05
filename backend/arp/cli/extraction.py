from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from arp.cli._shared import _registry, _run_store, _xbrl_source
from arp.config import get_settings
from arp.extraction.financials_pipeline import run_financials_extraction
from arp.extraction.pipeline import run_extraction
from arp.extraction.schema_builder import draft_schema
from arp.extraction.tnfd_pipeline import run_tnfd_extraction
from arp.llm.factory import build_llm_client, build_verifier_llm_client
from arp.schemas.datapoints import DataPointSchema
from arp.universe import load_company_universe

extract_app = typer.Typer(help="Schema-driven data-point extraction.")


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
    verifier_llm = build_verifier_llm_client(settings)
    schema = DataPointSchema.model_validate_json(schema_file.read_text())
    companies = load_company_universe(universe)
    typer.echo(f"Extracting schema '{schema.name}' ({len(schema.fields)} fields) across {len(companies)} companies...")
    run_id = asyncio.run(
        run_extraction(
            schema, companies, llm=llm, verifier_llm=verifier_llm, registry=_registry(), settings=settings, run_store=_run_store()
        )
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
    verifier_llm = build_verifier_llm_client(settings)
    companies = load_company_universe(universe)
    typer.echo(f"Extracting segments/CapEx/R&D across {len(companies)} companies...")
    run_id = asyncio.run(
        run_financials_extraction(
            companies,
            llm=llm,
            verifier_llm=verifier_llm,
            registry=_registry(),
            settings=settings,
            run_store=_run_store(),
            xbrl_source=_xbrl_source() if settings.xbrl_facts_enabled else None,
        )
    )
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
    run_id = asyncio.run(
        run_tnfd_extraction(
            companies, as_of, llm=llm, verifier_llm=verifier_llm, registry=_registry(), settings=settings, run_store=_run_store()
        )
    )
    typer.echo(f"Run complete: {run_id} (see runs/{run_id}/)")
