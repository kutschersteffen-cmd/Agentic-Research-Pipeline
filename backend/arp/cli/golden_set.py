from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from arp.config import get_settings
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
