from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from arp.config import get_settings
from arp.golden_set.planner_runner import build_demo_context, load_planner_cases, run_planner_set
from arp.golden_set.role_runner import load_role_cases as load_role_golden_set_cases
from arp.golden_set.role_runner import run_role_golden_set
from arp.golden_set.runner import load_cases as load_golden_set_cases
from arp.golden_set.runner import run_golden_set
from arp.llm.factory import build_llm_client, build_verifier_llm_client

golden_set_app = typer.Typer(help="Golden-set regression testing for the extraction pipeline -- run before every prompt/model change reaches a real batch.")


@golden_set_app.command("run")
def golden_set_run(
    cases_file: Path = typer.Option(
        None, "--cases", help="Custom golden-set JSON file (same shape as the bundled set). Defaults to the bundled set."
    ),
    fail_on_regression: bool = typer.Option(
        True, help="Exit with a non-zero status if any case fails -- for wiring into CI before a prompt/model change ships."
    ),
) -> None:
    """Runs the golden set (manually verified extractions) through the real
    extractor -> independent-verifier -> programmatic-grounding pipeline
    and reports pass/fail per case. Run this before any change to an
    extraction prompt or to llm_model/llm_verifier_model reaches a real
    batch -- a regression caught here is far cheaper than one discovered
    downstream in a 4000-company review queue."""
    settings = get_settings()
    llm = build_llm_client(settings)
    verifier_llm = build_verifier_llm_client(settings)
    cases = load_golden_set_cases(cases_file)
    typer.echo(f"Running {len(cases)} golden-set case(s) against {settings.llm_model} / verifier {settings.llm_verifier_model}...")
    report = asyncio.run(
        run_golden_set(
            cases,
            llm=llm,
            verifier_llm=verifier_llm,
            fuzzy_threshold=settings.grounding_fuzzy_threshold,
            confidence_review_threshold=settings.confidence_review_threshold,
        )
    )
    for result in report.results:
        status = "PASS" if result.passed else "FAIL"
        typer.echo(f"[{status}] {result.case_id}: {result.description}")
        if not result.passed:
            typer.echo(f"       {result.detail}")
    typer.echo(f"\n{report.passed}/{report.total} passed (extractor={report.extractor_model}, verifier={report.verifier_model}).")
    if fail_on_regression and not report.all_passed:
        raise typer.Exit(1)


@golden_set_app.command("planner")
def golden_set_planner(
    cases_file: Path = typer.Option(
        None, "--cases", help="Custom planner-case JSON file (same shape as the bundled set). Defaults to the bundled set."
    ),
    repair: bool = typer.Option(
        False, "--repair", help="Also allow the bounded re-plan pass, measuring end-to-end behaviour instead of the first plan."
    ),
    fail_on_regression: bool = typer.Option(
        True, help="Exit non-zero if any case fails -- for wiring into CI before a planning-prompt change ships."
    ),
) -> None:
    """Runs the generative-BI planner against briefs with known-correct
    dashboard *shapes* (which kinds, metrics, dimensions and fields must
    appear), scored against the bundled demo dataset so the run is
    reproducible anywhere. The counterpart of `golden-set run` for
    planning rather than extraction: run it before any change to the
    planning prompt, the dimension/metric vocabulary, or the planner's
    model reaches real briefs. Requires ARP_ANTHROPIC_API_KEY."""
    llm = build_llm_client(get_settings())
    cases = load_planner_cases(cases_file)
    typer.echo(f"Running {len(cases)} planner case(s) against {get_settings().llm_model} (repair={'on' if repair else 'off'})...")

    async def _run():
        ctx = await build_demo_context()
        return await run_planner_set(cases, llm=llm, ctx=ctx, repair=repair)

    report = asyncio.run(_run())
    for result in report.results:
        typer.echo(f"[{'PASS' if result.passed else 'FAIL'}] {result.case_id}: {result.description}")
        for panel in result.panels:
            typer.echo(f"       panel: {panel}")
        if result.clarification:
            typer.echo(f"       clarification: {result.clarification}")
        for failure in result.failures:
            typer.echo(f"       ! {failure}")
    typer.echo(f"\n{report.passed}/{report.total} passed (model={report.model}).")
    if fail_on_regression and not report.all_passed:
        raise typer.Exit(1)


@golden_set_app.command("run-roles")
def golden_set_run_roles(
    cases_file: Path = typer.Option(
        None, "--cases", help="Custom role golden-set JSON file (same shape as the bundled set). Defaults to the bundled set."
    ),
    fail_on_regression: bool = typer.Option(
        True, help="Exit with a non-zero status if any case fails -- for wiring into CI before a role-classification prompt/model change ships."
    ),
) -> None:
    """Runs roadmap G4's company-role golden set through the real
    `classify_company_role` function and reports pass/fail per case. Run
    this before any change to the role-classification prompt or model
    reaches a real scan, mirroring `arp golden-set run` for the extraction
    pipeline."""
    settings = get_settings()
    llm = build_llm_client(settings)
    cases = load_role_golden_set_cases(cases_file)
    typer.echo(f"Running {len(cases)} role golden-set case(s) against {settings.llm_model}...")
    report = asyncio.run(run_role_golden_set(cases, llm=llm))
    for result in report.results:
        status = "PASS" if result.passed else "FAIL"
        typer.echo(f"[{status}] {result.case_id}: {result.description}")
        if not result.passed:
            typer.echo(f"       {result.detail}")
    typer.echo(f"\n{report.passed}/{report.total} passed.")
    if fail_on_regression and not report.all_passed:
        raise typer.Exit(1)
