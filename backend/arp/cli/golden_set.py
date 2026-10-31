from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer
from pydantic import ValidationError

from arp.api.auth import Principal
from arp.bi.eval import load_bi_cases, run_bi_set
from arp.cli._shared import _run_store
from arp.config import get_settings
from arp.extraction.pipeline import load_run_schema
from arp.golden_set.export import export_cases
from arp.golden_set.precision import load_record_cases, run_precision
from arp.golden_set.retrieval import run_cases_retrieval_eval, run_retrieval_eval
from arp.golden_set.role_runner import load_role_cases as load_role_golden_set_cases
from arp.golden_set.role_runner import run_role_golden_set
from arp.golden_set.runner import load_cases as load_golden_set_cases
from arp.golden_set.runner import run_golden_set
from arp.llm.factory import build_llm_client, build_verifier_llm_client
from arp.presets.registry import PRESETS
from arp.review.items import list_open_items
from arp.review.quality import seed_known_answers
from arp.schemas.review import ReviewDecision

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


@golden_set_app.command("bi")
def golden_set_bi(
    cases_file: Path = typer.Option(None, "--cases", help="Custom BI-case JSON file (same shape as the bundled set)."),
    fail_on_regression: bool = typer.Option(True, help="Exit non-zero if any case fails."),
) -> None:
    """Runs the Superset chart planner against briefs with known-correct
    shapes (datasets, viz types, metrics, or a refusal). Needs no Superset:
    metas are built offline from the catalog. Requires ARP_ANTHROPIC_API_KEY;
    not run in CI."""
    llm = build_llm_client(get_settings())
    cases = load_bi_cases(cases_file)
    typer.echo(f"Running {len(cases)} BI case(s) against {get_settings().llm_model}...")
    results = asyncio.run(run_bi_set(cases, llm=llm))
    for r in results:
        typer.echo(f"[{'PASS' if r.passed else 'FAIL'}] {r.brief}")
        for f in r.failures:
            typer.echo(f"       ! {f}")
    passed = sum(r.passed for r in results)
    typer.echo(f"\n{passed}/{len(results)} passed.")
    if fail_on_regression and passed != len(results):
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


@golden_set_app.command("seed-known-answers")
def golden_set_seed_known_answers(
    count: int = typer.Option(
        None, "--count", min=1, help="Items to seed. Defaults to known_answer_rate times the open review items (at least 1)."
    ),
    seed: int = typer.Option(None, "--seed", help="Random seed, for a repeatable choice of cases."),
) -> None:
    """Seeds known-answer items into the review queue as one trial extraction run: half carry
    the gold value, half a wrong copy. Which items they are is kept in review_quality_dir only;
    reviewers see ordinary items. Accuracy shows per reviewer in GET /api/review/quality."""
    settings = get_settings()
    run_store = _run_store()
    if count is None:
        system = Principal(user_id="system", name="system", role="approver")
        count = max(1, round(settings.known_answer_rate * len(list_open_items(run_store, system))))
    run_id = seed_known_answers(run_store, settings, count=count, seed=seed)
    typer.echo(f"Seeded {count} known-answer item(s) in trial run {run_id}.")


@golden_set_app.command("precision")
def golden_set_precision(
    schema_id: str = typer.Option(..., "--schema", help="Preset id of the schema to extract."),
    cases_file: Path = typer.Option(..., "--cases", help="JSON array of RecordGoldenCase objects (hand-checked answers per company)."),
    documents_dir: Path = typer.Option(..., "--documents-dir", help="Directory holding <company_id>/ document folders."),
    min_precision: float = typer.Option(0.97, help="Exit non-zero if the precision of auto-accepted values falls below this."),
) -> None:
    """Extracts whole records for hand-checked companies and reports how many auto-accepted
    values are right -- routed as if every field were released and audited."""
    if schema_id not in PRESETS:
        typer.echo(f"Unknown preset: {schema_id}. Known: {', '.join(PRESETS)}", err=True)
        raise typer.Exit(1)
    settings = get_settings()
    report = asyncio.run(
        run_precision(
            load_record_cases(cases_file),
            schema=PRESETS[schema_id](),
            documents_dir=documents_dir,
            llm=build_llm_client(settings),
            verifier_llm=build_verifier_llm_client(settings),
            settings=settings,
        )
    )
    for w in report.wrong_auto_accepted:
        typer.echo(f"WRONG {w['case_id']} {w['field_id']}: expected {w['expected']!r}, got {w['actual']!r}")
    precision = "n/a (nothing auto-accepted)" if report.precision is None else f"{report.precision:.1%}"
    typer.echo(
        f"{report.schema_id}: precision {precision} ({report.auto_accepted_correct}/{report.auto_accepted} auto-accepted), "
        f"coverage {report.coverage:.1%}, review rate {report.review_rate:.1%} of {report.total}."
    )
    if report.auto_accepted == 0:  # nothing to measure: a run that auto-accepts nothing cannot pass the gate
        typer.echo("FAIL: no value was auto-accepted, so precision is unmeasured.", err=True)
        raise typer.Exit(1)
    if report.precision < min_precision:
        raise typer.Exit(1)


def _decisions(run_store, run_id: str) -> list[ReviewDecision]:
    decisions, legacy = [], 0
    for r in run_store.read_decisions(run_id):
        try:
            decisions.append(ReviewDecision.model_validate(r))
        except ValidationError:  # a pre-step row (e.g. decision "edit", no user_id): no final-state info to export
            legacy += 1
    if legacy:
        typer.echo(f"Skipped {legacy} legacy decision row(s) that do not match the current review schema.", err=True)
    return decisions


@golden_set_app.command("export-labels")
def golden_set_export_labels(
    run_id: str = typer.Option(..., "--run-id", help="Extraction run whose review decisions become labelled cases."),
    out: Path = typer.Option(..., "--out", help="File to write the JSON array of RecordGoldenCase objects to."),
) -> None:
    """Turns a run's reviewer decisions (approve, correct, reject as not disclosed) into cases for
    `golden-set precision`. Escalated and other rejected items are left out."""
    run_store = _run_store()
    decisions = _decisions(run_store, run_id)
    cases = export_cases(run_store, run_id, decisions, schema=load_run_schema(run_store, run_id))
    out.write_text(json.dumps([c.model_dump(mode="json") for c in cases], indent=2))
    typer.echo(f"Wrote {len(cases)} case(s), {sum(len(c.expected) for c in cases)} labelled value(s), to {out}.")


@golden_set_app.command("retrieval")
def golden_set_retrieval(
    run_id: str = typer.Option(None, "--run-id", help="Reviewed extraction run whose approved citations are the gold spans."),
    cases_file: Path = typer.Option(None, "--cases", help="Committed retrieval cases file (gold spans as text); no Postgres needed."),
    documents_dir: Path = typer.Option(
        None, "--documents-dir",
        help="Directory holding <company_id>/ document folders. Defaults to the app's, or the cases file's documents/ sibling.",
    ),
    min_recall: float = typer.Option(None, "--min-recall", min=0.0, max=1.0, help="Exit 1 if recall@evidence_max_chunks is below this."),
    hybrid: bool = typer.Option(None, "--hybrid/--no-hybrid", help="Override hybrid_retrieval_enabled."),
    rerank: bool = typer.Option(None, "--rerank/--no-rerank", help="Override rerank_enabled."),
    rerank_candidates: int = typer.Option(None, "--rerank-candidates", min=1, help="Override rerank_candidates."),
    out: Path = typer.Option(None, "--out", help="Also write the JSON report here."),
) -> None:
    """Replays each reviewed field's evidence selection and reports how often it contains the span a
    reviewer approved (recall@5 and @evidence_max_chunks), plus seconds per field. No LLM calls.
    With --cases, the gold spans come from a committed cases file instead of a reviewed run."""
    if (run_id is None) == (cases_file is None):
        typer.echo("Pass exactly one of --cases or --run-id.", err=True)
        raise typer.Exit(2)
    settings = get_settings()
    overrides = {"hybrid_retrieval_enabled": hybrid, "rerank_enabled": rerank, "rerank_candidates": rerank_candidates}
    settings = settings.model_copy(update={k: v for k, v in overrides.items() if v is not None})
    try:
        if cases_file is not None:
            report = asyncio.run(run_cases_retrieval_eval(
                cases_file, documents_dir=documents_dir or cases_file.parent / "documents", settings=settings,
            ))
        else:
            run_store = _run_store()
            report = asyncio.run(
                run_retrieval_eval(
                    run_store, run_id, _decisions(run_store, run_id),
                    documents_dir=documents_dir or settings.documents_dir, settings=settings,
                )
            )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if out:
        out.write_text(json.dumps(report, indent=2))
    if report["stale_spans"]:
        typer.echo(f"Left out {report['stale_spans']} span(s) whose text no longer matches the current parse.", err=True)
    if not report["gold_spans"]:
        typer.echo("No approved, grounded citations that match the current parse: review some items first.", err=True)
        raise typer.Exit(1)
    k = settings.evidence_max_chunks
    typer.echo(
        f"{report['gold_spans']} gold span(s) over {report['fields_ranked']} field(s): recall@5 {report['recall_at_5']:.1%}, "
        f"recall@{k} {report[f'recall_at_{k}']:.1%}; {report['median_seconds_per_field']:.2f}s median, "
        f"{report['max_seconds_per_field']:.2f}s max per field."
    )
    if min_recall is not None and report[f"recall_at_{k}"] < min_recall:
        typer.echo(f"recall@{k} {report[f'recall_at_{k}']:.1%} is below the minimum {min_recall:.1%}.", err=True)
        raise typer.Exit(1)
