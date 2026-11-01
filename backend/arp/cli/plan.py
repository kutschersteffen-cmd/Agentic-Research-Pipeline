from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from arp.orchestration.plan_check import check_script
from arp.orchestration.plan_interp import PlanScriptError, StepLimitExceeded, dry_run
from arp.orchestration.plan_planner import PlanRejected, draft_plan
from arp.orchestration.plan_store import PlanStore

plan_app = typer.Typer(help="Research Orchestrator: draft, check, approve and run plan scripts.")


@plan_app.command("check")
def check(path: Path) -> None:
    """Check a plan script against the allowed subset of Python."""
    errors = check_script(path.read_text())
    if errors:
        typer.echo("\n".join(errors))
        raise typer.Exit(1)
    typer.echo("ok")


@plan_app.command("dry-run")
def dry_run_cmd(target: str) -> None:
    """List the steps a plan script (a file) or a stored plan (its id) will take, without starting any run."""
    path = Path(target)
    if not path.exists():
        _print_steps(_plan_or_exit(_store(), target)["dry_run"])
        return
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


def _plan_or_exit(store: PlanStore, plan_id: str) -> dict:
    from arp.orchestration.plan_store import PlanNotFound

    try:
        return store.get(plan_id)
    except PlanNotFound as exc:
        typer.echo(f"Unknown plan: {plan_id}")
        raise typer.Exit(1) from exc


@plan_app.command("show")
def show(plan_id: str) -> None:
    """Show a plan's status, script, dry run and the calls its run made."""
    store = _store()
    plan = _plan_or_exit(store, plan_id)
    typer.echo(f"{plan['id']}  {plan['status']}" + (f"  approved by {plan['approved_by']}" if plan["approved_by"] else ""))
    typer.echo(plan["script"])
    _print_steps(plan["dry_run"])
    for c in store.calls(plan_id):
        typer.echo(f"call {c['seq']} {c['kind']} {c['status']} {c['run_id'] or c['result_ref'] or ''}".rstrip())


@plan_app.command("approve")
def approve(plan_id: str, user: str = typer.Option(..., "--user", help="Who approves the plan.")) -> None:
    store = _store()
    if _plan_or_exit(store, plan_id)["status"] != "draft":
        typer.echo("only a draft plan can be approved")
        raise typer.Exit(1)
    store.approve(plan_id, user)
    typer.echo("approved")


def _runtime():
    from arp.api.routers.plans import build_runtime
    from arp.config import get_settings

    return build_runtime(get_settings())


@plan_app.command("run")
def run(plan_id: str) -> None:
    """Run an approved plan in the foreground until it ends."""
    from arp.orchestration.plan_executor import PlanNotRunnable, run_plan

    store = _store()
    _plan_or_exit(store, plan_id)
    steps, reviewed = _runtime()
    try:
        status = run_plan(plan_id, store, steps, reviewed)
    except PlanNotRunnable as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc
    typer.echo(status)
    if status == "failed":
        typer.echo(store.get(plan_id)["error"] or "")
        raise typer.Exit(1)


@plan_app.command("resume")
def resume(plan_id: str) -> None:
    """Run a failed plan again; steps that already finished are not repeated."""
    run(plan_id)


@plan_app.command("cancel")
def cancel(plan_id: str) -> None:
    """The step in progress finishes; no later step starts."""
    from arp.orchestration.plan_executor import PlanNotRunnable, cancel_plan

    store = _store()
    _plan_or_exit(store, plan_id)
    try:
        cancel_plan(plan_id, store)
    except PlanNotRunnable as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc
    typer.echo("cancelled")


DEMO_BRIEF = "Demo: EU grid storage, green capex for significant names, scored, as a report"
DEMO_SCRIPT = """u = universe_build(taxonomy_id="tax_demo_grid_storage", source="data/demo/universe.csv")
e = extraction(universe_run_id=u.run_id, schema_id="green_capex",
               companies=[c.id for c in u.companies if c.exposure in ["pure_play", "significant"]])
d = decision_score(source_run_id=e.run_id)
report_render(source_ids=[e.run_id])
"""


@plan_app.command("seed-demo")
def seed_demo() -> None:
    """Store a demo plan (script and dry run, no LLM call) to show the Plans page."""
    store = _store()
    plan_id = store.create(DEMO_BRIEF, DEMO_SCRIPT)
    typer.echo(plan_id)
    _print_steps(store.get(plan_id)["dry_run"])
