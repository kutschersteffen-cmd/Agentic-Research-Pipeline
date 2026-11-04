from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from arp.orchestration.plan_check import check_script
from arp.orchestration.plan_interp import PlanScriptError, StepLimitExceeded, dry_run
from arp.orchestration.plan_planner import PlanRejected, draft_plan, replan_plan
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
    from arp.api.deps import get_decision_store, get_index_store
    from arp.config import get_settings
    from arp.orchestration.plan_planner import planner_context
    from arp.storage.taxonomy_store import TaxonomyStore

    return planner_context(TaxonomyStore(get_settings().taxonomies_dir).list_all(),
                           get_decision_store().list_frameworks(), get_index_store().list_calibrations())


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


@plan_app.command("replan")
def replan(plan_id: str, user: str | None = typer.Option(None, "--user", help="Who asks for the re-plan.")) -> None:
    """Have the planner rewrite a failed plan's remaining work; finished steps are kept. Stores it as a draft."""
    from arp.orchestration.plan_store import PlanNotReplannable

    store = _store()
    _plan_or_exit(store, plan_id)
    try:
        asyncio.run(replan_plan(plan_id, _llm(), store, _context(), user))
    except (PlanRejected, PlanNotReplannable) as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc
    plan = store.get(plan_id)
    typer.echo(f"version {plan['version']}")
    _print_steps(plan["dry_run"])


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


DEMO_BRIEF = "Demo: build the demo index, then EU grid storage green capex as a report"
DEMO_REVIEW_DATE = "2026-10-31"


def _demo_script(calibration_id: str, candidates: str) -> str:
    # Step 1 needs no model or network, so it really finishes in any environment; the later steps need a
    # ratified taxonomy and the model, so outside a configured install they fail and show that state too.
    return f"""i = index_construct(calibration_id="{calibration_id}", candidates="{candidates}", review_date="{DEMO_REVIEW_DATE}")
u = universe_build(taxonomy_id="tax_demo_grid_storage", source="data/demo/universe.csv")
e = extraction(universe_run_id=u.run_id, schema_id="green_capex",
               companies=[c.id for c in u.companies if c.exposure in ["pure_play", "significant"]])
report_render(source_ids=[e.run_id])
"""


DEMO_REPLANNED_BRIEF = "Demo (re-planned): build the demo index, then EU grid storage green capex as a report"
DEMO_OLD_SCRIPT = """u = universe_build(taxonomy_id="tax_demo_grid_storage_v0", source="data/demo/universe.csv")
e = extraction(universe_run_id=u.run_id, schema_id="green_capex")
report_render(source_ids=[e.run_id])
"""
DEMO_OLD_ERROR = "step 1 universe_build failed: taxonomy tax_demo_grid_storage_v0 is not ratified"


@plan_app.command("seed-demo")
def seed_demo(replanned: bool = typer.Option(False, "--replanned",
                                             help="Store the plan already re-planned once (version 2).")) -> None:
    """Store a demo plan (no LLM call) to show the Plans page, with a demo index calibration and candidates file so
    its first step runs to done. With --replanned the plan is at version 2, its failed first script under previous
    versions."""
    import json

    from arp.api.deps import get_index_store
    from arp.config import get_settings
    from arp.index.mock_data import demo_universe
    from arp.index.presets import build_preset

    index_store = get_index_store()
    calibration = index_store.create_calibration("Plans demo (exclusion only)", build_preset("exclusion_only"),
                                                 effective_from="2026-01-01", notes="Seeded by arp plan seed-demo.",
                                                 created_by="plans-demo")
    index_store.approve_calibration(calibration.calibration_id, "plans-demo-reviewer")
    candidates = get_settings().indices_dir / "plans_demo_candidates.json"
    candidates.parent.mkdir(parents=True, exist_ok=True)
    candidates.write_text(json.dumps([c.model_dump(mode="json") for c in demo_universe()]))

    store = _store()
    script = _demo_script(calibration.calibration_id, str(candidates))
    if replanned:
        old = {"version": 1, "script": DEMO_OLD_SCRIPT, "error": DEMO_OLD_ERROR, "replanned_at": "2026-10-31T09:00:00+00:00",
               "replanned_by": "plans-demo"}
        plan_id = store.create(DEMO_REPLANNED_BRIEF, script, previous_scripts=[old])
    else:
        plan_id = store.create(DEMO_BRIEF, script)
    typer.echo(plan_id)
    _print_steps(store.get(plan_id)["dry_run"])


@plan_app.command("golden")
def golden(
    cases: Path = typer.Option(..., "--cases", help="JSONL: {id, brief, expected_kinds}."),
    min_pass: int = typer.Option(..., "--min-pass", help="Fail unless at least this many cases pass."),
) -> None:
    """Run the planner on known briefs; a case passes when its script is accepted and its dry run takes the
    expected step kinds in that order (other steps allowed in between)."""
    from arp.orchestration.plan_golden import load_cases, run_case

    async def _all() -> list[tuple[str, bool, str]]:
        llm = _llm()
        return [(c["id"], *(await run_case(c, llm))) for c in load_cases(cases)]

    results = asyncio.run(_all())
    for case_id, ok, detail in results:
        typer.echo(f"{'pass' if ok else 'FAIL'}  {case_id}: {detail}")
    passed = sum(ok for _, ok, _ in results)
    typer.echo(f"{passed}/{len(results)} passed (need {min_pass})")
    if passed < min_pass:
        raise typer.Exit(1)
