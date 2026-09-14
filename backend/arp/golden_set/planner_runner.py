from __future__ import annotations

import json
import tempfile
from pathlib import Path

from arp.golden_set.planner_schema import PlannerCase, PlannerCaseResult, PlannerReport
from arp.llm.base import LLMClient
from arp.portfolio.climate.schemas import build_climate_schema
from arp.portfolio.genbi import planner
from arp.portfolio.genbi.planner import PlannerContext
from arp.portfolio.genbi.schemas import DashboardSpec, PanelSpec
from arp.portfolio.mock_data import generate_demo_dataset
from arp.schemas.common import now_iso
from arp.storage.portfolio_store import PortfolioStore

_BUNDLED_CASES_PATH = Path(__file__).parent / "data" / "planner_cases.json"


def load_planner_cases(path: Path | None = None) -> list[PlannerCase]:
    """Loads the bundled planner cases by default, or a deployment's own
    file of the same shape -- the same growth path the extraction golden
    set has: cases accumulate from real briefs that went wrong."""
    raw = json.loads((path or _BUNDLED_CASES_PATH).read_text())
    return [PlannerCase.model_validate(c) for c in raw]


async def build_demo_context() -> PlannerContext:
    """The fixed context every bundled case is written against: the demo
    dataset seeded into a throwaway store. Deterministic (`mock_data.py`
    seeds every figure off the company id) and independent of whatever a
    given deployment holds, which is what makes a regression here a
    statement about the prompt rather than about the data.

    Worked examples are deliberately absent -- a fresh store has no saved
    dashboards -- so the harness measures the base prompt, not whatever
    few-shot material a deployment has accumulated.
    """
    with tempfile.TemporaryDirectory() as tmp:
        store = PortfolioStore(Path(tmp))
        await generate_demo_dataset(store)
        securities = store.list_securities()
        return planner.build_context(
            portfolios=store.list_portfolios(),
            companies=store.list_companies(),
            securities_asset_classes=[s.asset_class for s in securities],
            snapshot_dates=store.all_snapshot_dates(),
            schema=build_climate_schema(),
        )


def _dimensions_of(panel: PanelSpec) -> set[str]:
    return {panel.row_dim, panel.col_dim} if panel.kind == "pivot" else {panel.group_by}


def evaluate_case(
    case: PlannerCase, spec: DashboardSpec | None, clarification: str, warnings: list[str]
) -> PlannerCaseResult:
    """Scores one planned dashboard against one case's assertions. Pure and
    LLM-free, so the scoring itself is testable without a model."""
    failures: list[str] = []
    panels = list(spec.panels) if spec else []

    if not case.expect_understood:
        if spec is not None:
            failures.append(f"Expected the planner to ask for clarification; it planned {len(panels)} panel(s) instead.")
        elif case.expect_clarification_contains and case.expect_clarification_contains.lower() not in clarification.lower():
            failures.append(f"Clarification {clarification!r} does not mention {case.expect_clarification_contains!r}.")
    elif spec is None:
        failures.append(f"Expected a dashboard; the planner asked for clarification instead ({clarification!r}).")
    else:
        if len(panels) < case.min_panels:
            failures.append(f"Expected at least {case.min_panels} panel(s), got {len(panels)}.")
        if len(panels) > case.max_panels:
            failures.append(f"Expected at most {case.max_panels} panel(s), got {len(panels)}.")

        kinds = {p.kind for p in panels}
        for kind in case.require_kinds:
            if kind not in kinds:
                failures.append(f"No panel of kind {kind!r} (got: {', '.join(sorted(kinds)) or 'none'}).")

        metrics = {p.metric for p in panels}
        for metric in case.require_metrics:
            if metric not in metrics:
                failures.append(f"No panel using metric {metric!r} (got: {', '.join(sorted(metrics)) or 'none'}).")

        dimensions = {d for p in panels for d in _dimensions_of(p) if d}
        for dimension in case.require_dimensions:
            if dimension not in dimensions:
                failures.append(f"No panel grouped or pivoted on {dimension!r} (got: {', '.join(sorted(dimensions)) or 'none'}).")

        field_ids = {p.data_point_field_id for p in panels if p.data_point_field_id}
        for field_id in case.require_field_ids:
            if field_id not in field_ids:
                failures.append(f"No panel aggregating field {field_id!r} (got: {', '.join(sorted(field_ids)) or 'none'}).")

        if case.require_portfolio_filter:
            wanted = set(case.require_portfolio_filter)
            if not any(set(p.portfolio_filter) == wanted for p in panels):
                failures.append(f"No panel restricted to portfolio(s) {', '.join(sorted(wanted))}.")

    if case.forbid_rejected_panels and warnings:
        failures.append(f"Planner produced {len(warnings)} panel(s) that failed validation: {warnings[0]}")

    return PlannerCaseResult(
        case_id=case.case_id,
        description=case.description,
        passed=not failures,
        failures=failures,
        panel_count=len(panels),
        panels=[planner._summarize_panel(p) for p in panels],
        warnings=warnings,
        clarification=clarification,
    )


async def run_planner_set(
    cases: list[PlannerCase], *, llm: LLMClient, ctx: PlannerContext, repair: bool = False
) -> PlannerReport:
    """Runs every case through the real planner and scores the resulting
    plan's shape.

    `repair=False` by default: the harness measures what the *first* plan
    got right, which is what a prompt change actually moves. Turn it on to
    measure the end-to-end behaviour an analyst sees, including the bounded
    re-plan pass.

    Run this before any change to the planning prompt, the dimension or
    metric vocabulary, or the planner's model reaches real briefs -- the
    same argument `arp golden-set run` makes for extraction.
    """
    results: list[PlannerCaseResult] = []
    model: str | None = None
    for case in cases:
        spec, clarification, warnings, usage = await planner.plan_dashboard(case.brief, llm, ctx, repair=repair)
        model = model or (usage.model or None)
        results.append(evaluate_case(case, spec, clarification, warnings))

    return PlannerReport(
        total=len(results),
        passed=sum(1 for r in results if r.passed),
        failed_case_ids=[r.case_id for r in results if not r.passed],
        results=results,
        run_at=now_iso(),
        model=model,
        repair_enabled=repair,
    )
