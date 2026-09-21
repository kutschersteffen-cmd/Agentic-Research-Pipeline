from __future__ import annotations

from arp.llm.base import LLMClient, LLMUsage
from arp.portfolio import analytics as analytics_store
from arp.portfolio.climate.schemas import build_climate_schema
from arp.portfolio.genbi import narrator, observations, planner
from arp.portfolio.genbi.executor import execute_panel
from arp.portfolio.genbi.schemas import DashboardSpec, GeneratedDashboard, Narrative
from arp.storage.portfolio_store import PortfolioStore, portfolio_directories


def save_dashboard(store: PortfolioStore, spec: DashboardSpec) -> None:
    store.save_dashboard(spec.model_dump(mode="json"))


def list_dashboards(store: PortfolioStore) -> list[DashboardSpec]:
    return [DashboardSpec.model_validate(row) for row in store.list_dashboards()]


def get_dashboard(store: PortfolioStore, dashboard_id: str) -> DashboardSpec | None:
    row = store.get_dashboard(dashboard_id)
    return DashboardSpec.model_validate(row) if row else None


def run_dashboard(
    spec: DashboardSpec,
    store: PortfolioStore,
    *,
    as_of: str | None = None,
) -> GeneratedDashboard:
    """Executes a dashboard spec with **no LLM involved at all**: every
    panel is computed, every fact derived, and the commentary is the
    deterministic fact text.

    This is what makes a generated dashboard a report rather than a
    conversation -- the same spec re-run next quarter recomputes the same
    panels against the newer snapshot, with no model call, no variation,
    and nothing that can drift between runs except the underlying holdings.
    `as_of` overrides the panels' own snapshot dates so a whole dashboard
    can be re-pointed at one date in a single call.
    """
    securities, companies = portfolio_directories(store)
    panels = []
    warnings: list[str] = []
    for panel in spec.panels:
        target = panel.model_copy(update={"as_of": as_of}) if as_of and panel.kind != "trend" else panel
        result = execute_panel(target, store, securities, companies)
        if result.error:
            warnings.append(f"Panel {panel.title!r} failed to execute: {result.error}")
        panels.append(result)

    dashboard_facts = observations.facts_for_news_flags(store.list_flags())
    resolved_as_of = next((p.as_of for p in panels if p.as_of), "")
    # The deterministic headline takes each panel's lead fact rather than
    # the first N facts overall, so a four-panel dashboard reads as four
    # findings instead of one panel's details plus its neighbour's total.
    lead_facts = [panel.facts[0] for panel in panels if panel.facts] + dashboard_facts
    return GeneratedDashboard(
        spec=spec,
        as_of=resolved_as_of,
        panels=panels,
        headline=Narrative(text=narrator.deterministic_text(lead_facts, limit=4), grounded=True, source="deterministic_fallback"),
        panel_narratives={
            p.panel.panel_id: Narrative(text=narrator.deterministic_text(p.facts), grounded=True, source="deterministic_fallback")
            for p in panels
        },
        warnings=warnings,
    )


async def generate_dashboard(
    brief: str,
    llm: LLMClient,
    store: PortfolioStore,
    *,
    narrate: bool = True,
    save: bool = False,
    repair: bool = True,
) -> tuple[GeneratedDashboard, LLMUsage]:
    """The full generative-BI pass: brief -> plan -> compute -> narrate.

    The three stages are deliberately separate and only the first and last
    involve a model, neither of which ever sees or produces a portfolio
    figure directly. `repair=False` disables the planner's single bounded
    re-plan attempt on rejected panels (used by the planner eval set, which
    measures the first plan rather than the repaired one). The planner chooses what to look at; the deterministic
    engine computes every number; the narrator writes prose that is then
    checked, token by token, back against those computed numbers. What
    persists is the plan, not the prose -- so the dashboard can be re-run
    later with `run_dashboard`, with no model in the loop at all.
    """
    securities, _companies = portfolio_directories(store)
    ctx = planner.build_context(
        portfolios=store.list_portfolios(),
        companies=store.list_companies(),
        securities_asset_classes=[s.asset_class for s in securities.values()],
        snapshot_dates=store.all_snapshot_dates(),
        schema=build_climate_schema(),
        # Dashboards and analytics a human chose to save become worked
        # examples for the next brief -- the deployment's own accepted plans
        # are better few-shot material than anything written into a prompt,
        # and they accumulate the same way the extraction golden set does.
        saved_dashboards=list_dashboards(store),
        saved_analytics=analytics_store.list_analytics(store),
    )
    spec, clarification, plan_warnings, usage = await planner.plan_dashboard(brief, llm, ctx, repair=repair)
    if spec is None:
        return (
            GeneratedDashboard(
                spec=DashboardSpec(title="(not planned)", brief=brief),
                clarification_needed=clarification,
                warnings=plan_warnings,
            ),
            usage,
        )

    dashboard = run_dashboard(spec, store)
    dashboard.warnings = plan_warnings + dashboard.warnings
    total_usage = LLMUsage(
        input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, model=usage.model, prompt_version=usage.prompt_version
    )

    if narrate:
        dashboard_facts = observations.facts_for_news_flags(store.list_flags())
        headline, narratives, narrate_warnings, narrate_usage = await narrator.narrate(
            title=spec.title,
            brief=brief,
            goal=spec.goal,
            panels=dashboard.panels,
            dashboard_facts=dashboard_facts,
            llm=llm,
        )
        dashboard.headline = headline
        dashboard.panel_narratives = narratives
        dashboard.warnings = dashboard.warnings + narrate_warnings
        total_usage.input_tokens += narrate_usage.input_tokens
        total_usage.output_tokens += narrate_usage.output_tokens

    if save:
        save_dashboard(store, spec)
    return dashboard, total_usage
