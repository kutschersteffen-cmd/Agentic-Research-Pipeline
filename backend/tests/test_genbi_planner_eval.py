from arp.golden_set.planner_runner import build_demo_context, evaluate_case, load_planner_cases, run_planner_set
from arp.golden_set.planner_schema import PlannerCase
from arp.portfolio.genbi.planner import _PlannedDashboard, _PlannedPanel
from arp.portfolio.genbi.schemas import DashboardSpec, PanelSpec


def _spec(*panels: PanelSpec) -> DashboardSpec:
    return DashboardSpec(title="Planned", brief="b", panels=list(panels))


def test_bundled_planner_cases_load_and_are_unique():
    cases = load_planner_cases()
    assert len(cases) >= 5
    assert len({c.case_id for c in cases}) == len(cases)
    # every case says what failure it catches -- a case nobody can interpret
    # is a case nobody will fix
    assert all(c.description.strip() for c in cases)


async def test_demo_context_is_the_fixed_fixture_every_case_is_written_against():
    ctx = await build_demo_context()

    portfolio_ids = {p.portfolio_id for p in ctx.portfolios}
    assert {"sustainable_leaders", "core_equity_europe"} <= portfolio_ids
    assert "climate_carbon_intensity" in {fid for fid, _name in ctx.data_point_fields}
    assert len(ctx.snapshot_dates) >= 2
    # no worked examples: the harness measures the base prompt, not whatever
    # a deployment has accumulated
    assert ctx.examples == []


def test_shape_assertions_pass_when_the_plan_matches():
    case = PlannerCase(
        case_id="c",
        description="d",
        brief="climate overview of the sustainable leaders fund",
        min_panels=2,
        require_metrics=["weighted_avg_datapoint"],
        require_field_ids=["climate_carbon_intensity"],
        require_portfolio_filter=["sustainable_leaders"],
        require_kinds=["trend"],
        require_dimensions=["sector"],
    )
    spec = _spec(
        PanelSpec(
            title="Carbon intensity",
            group_by="sector",
            metric="weighted_avg_datapoint",
            data_point_field_id="climate_carbon_intensity",
            portfolio_filter=["sustainable_leaders"],
        ),
        PanelSpec(title="Trend", kind="trend", group_by="portfolio_id", metric="market_value_sum", date_range=("2026-01-01", "2026-04-01"), chart="line"),
    )

    result = evaluate_case(case, spec, "", [])
    assert result.passed and result.failures == []
    assert result.panel_count == 2


def test_each_unmet_assertion_is_reported_separately():
    case = PlannerCase(
        case_id="c",
        description="d",
        brief="b",
        min_panels=2,
        require_kinds=["trend"],
        require_metrics=["weighted_avg_datapoint"],
        require_dimensions=["sector"],
        require_field_ids=["climate_carbon_intensity"],
        require_portfolio_filter=["sustainable_leaders"],
    )
    spec = _spec(PanelSpec(title="Only one", group_by="country", metric="market_value_sum"))

    result = evaluate_case(case, spec, "", [])

    assert not result.passed
    assert len(result.failures) == 6  # panel count, kind, metric, dimension, field, portfolio scope
    assert any("at least 2 panel" in f for f in result.failures)
    assert any("sustainable_leaders" in f for f in result.failures)


def test_firm_wide_panel_does_not_satisfy_a_named_fund_brief():
    case = PlannerCase(case_id="c", description="d", brief="b", require_portfolio_filter=["sustainable_leaders"])
    firm_wide = _spec(PanelSpec(title="Carbon intensity", group_by="sector", metric="market_value_sum"))

    result = evaluate_case(case, firm_wide, "", [])

    # the right number for the wrong book is the failure this case exists for
    assert not result.passed
    assert any("restricted to portfolio" in f for f in result.failures)


def test_a_plan_with_rejected_panels_fails_even_when_the_shape_is_right():
    case = PlannerCase(case_id="c", description="d", brief="b", require_dimensions=["sector"])
    spec = _spec(PanelSpec(title="Good", group_by="sector", metric="market_value_sum"))

    assert evaluate_case(case, spec, "", []).passed
    scored = evaluate_case(case, spec, "", ["panel 'Bad': dropped -- unknown group_by 'mood'."])
    assert not scored.passed
    assert any("failed validation" in f for f in scored.failures)


def test_refusal_cases_score_the_opposite_way():
    case = PlannerCase(
        case_id="c", description="d", brief="show me the risk", expect_understood=False, expect_clarification_contains="portfolio"
    )

    asked = evaluate_case(case, None, "Which portfolio did you mean?", [])
    assert asked.passed

    guessed = evaluate_case(case, _spec(PanelSpec(title="Guess", group_by="sector", metric="market_value_sum")), "", [])
    assert not guessed.passed
    assert any("clarification" in f for f in guessed.failures)

    wrong_question = evaluate_case(case, None, "Which sector?", [])
    assert not wrong_question.passed


async def test_runner_scores_a_scripted_planner_end_to_end(fake_llm):
    cases = [
        PlannerCase(case_id="good", description="d", brief="sector exposure", require_dimensions=["sector"]),
        PlannerCase(case_id="bad", description="d", brief="sector exposure", require_kinds=["trend"]),
    ]
    plan = _PlannedDashboard(title="Sector view", panels=[_PlannedPanel(title="By sector", group_by="sector", metric="market_value_sum")])
    llm = fake_llm({"_PlannedDashboard": [plan, plan]})
    ctx = await build_demo_context()

    report = await run_planner_set(cases, llm=llm, ctx=ctx)

    assert report.total == 2 and report.passed == 1
    assert report.failed_case_ids == ["bad"]
    assert report.repair_enabled is False
    assert report.all_passed is False
    # the harness measures the first plan by default: no repair call was made
    assert llm.calls == ["_PlannedDashboard", "_PlannedDashboard"]
