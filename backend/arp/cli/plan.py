from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from arp.orchestration.plan_check import check_script
from arp.orchestration.plan_interp import PlanScriptError, StepLimitExceeded, dry_run
from arp.orchestration.plan_planner import PlanRejected, draft_plan
from arp.orchestration.plan_store import PlanStore

plan_app = typer.Typer(help="Research Orchestrator: check and dry-run plan scripts.")


@plan_app.command("check")
def check(path: Path) -> None:
    """Check a plan script against the allowed subset of Python."""
    errors = check_script(path.read_text())
    if errors:
        typer.echo("\n".join(errors))
        raise typer.Exit(1)
    typer.echo("ok")


@plan_app.command("dry-run")
def dry_run_cmd(path: Path) -> None:
    """List the steps a plan script will take, without starting any run."""
    # shortcut: takes a script file; `dry-run <plan_id>` arrives with plan storage (plan task 5).
    try:
        calls = dry_run(path.read_text())
    except (PlanScriptError, StepLimitExceeded) as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc
    _print_steps(calls)


def _store() -> PlanStore:
    from arp.config import get_settings
    from arp.db.session import require_dsn

    return PlanStore(require_dsn(get_settings()))


def _llm():
    from arp.config import get_settings
    from arp.llm.factory import build_llm_client

    return build_llm_client(get_settings())


def _context() -> str:
    from arp.api.deps import get_decision_store
    from arp.config import get_settings
    from arp.orchestration.plan_planner import planner_context
    from arp.storage.taxonomy_store import TaxonomyStore

    return planner_context(TaxonomyStore(get_settings().taxonomies_dir).list_all(),
                           get_decision_store().list_frameworks())


def _print_steps(calls: list[dict]) -> None:
    for c in calls:
        dep = f"  (depends on {c['depends_on']})" if c["depends_on"] else ""
        typer.echo(f"{c['seq']} {c['kind']} {c['params']}{dep}")


@plan_app.command("draft")
def draft(brief: str) -> None:
    """Have the planner write a plan script for a research brief; stores it as a draft."""
    store = _store()
    try:
        plan_id = asyncio.run(draft_plan(brief, _llm(), store, _context()))
    except PlanRejected as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc
    typer.echo(plan_id)
    _print_steps(store.get(plan_id)["dry_run"])
