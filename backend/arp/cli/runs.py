from __future__ import annotations

import json

import typer

from arp.cli._shared import _run_store
from arp.orchestration.job_manager import JobManager
from arp.research.pipeline import load_theme_run_matches, rank_theme_matches
from arp.research.results_diff import diff_theme_results
from arp.schemas.common import JobStatus

runs_app = typer.Typer(help="Inspect and export runs.")


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
