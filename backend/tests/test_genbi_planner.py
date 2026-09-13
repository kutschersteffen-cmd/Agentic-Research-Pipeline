from arp.portfolio.genbi import planner
from arp.portfolio.genbi.planner import _PlannedDashboard, _PlannedPanel
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Portfolio


def _ctx():
    return planner.build_context(
        portfolios=[Portfolio(portfolio_id="p1", name="Core Equity")],
        companies=[CompanyRef(company_id="bmw", name="BMW AG", sector="Automobiles", country="DE")],
        securities_asset_classes=["equity", "corporate_bond"],
        snapshot_dates=["2026-01-01", "2026-04-01"],
        schema=None,
    )


async def test_plan_dashboard_builds_validated_spec(fake_llm):
    planned = _PlannedDashboard(
        title="Equity exposure review",
        goal="Where the equity money sits",
        panels=[
            _PlannedPanel(title="By sector", question="Which sectors?", group_by="sector", metric="market_value_sum"),
            _PlannedPanel(title="Over time", kind="trend", group_by="portfolio_id", metric="market_value_sum", date_range=["2026-01-01", "2026-04-01"], chart="bar"),
        ],
    )
    llm = fake_llm({"_PlannedDashboard": [planned]})

    spec, clarification, warnings, _usage = await planner.plan_dashboard("Show me equity exposure", llm, _ctx())

    assert clarification == ""
    assert warnings == []
    assert [p.title for p in spec.panels] == ["By sector", "Over time"]
    assert spec.panels[1].date_range == ("2026-01-01", "2026-04-01")
    # a trend drawn as bars is a chart hint the planner got wrong, not a query error
    assert spec.panels[1].chart == "line"
    assert spec.brief == "Show me equity exposure"


async def test_invalid_panels_are_dropped_with_a_warning_never_coerced(fake_llm):
    planned = _PlannedDashboard(
        title="Mixed bag",
        panels=[
            _PlannedPanel(title="Good", group_by="sector", metric="market_value_sum"),
            _PlannedPanel(title="Bad dimension", group_by="industry_supersector", metric="market_value_sum"),
            _PlannedPanel(title="Bad metric", group_by="sector", metric="median_exposure"),
            _PlannedPanel(title="Unknown field", group_by="sector", metric="weighted_avg_datapoint", data_point_field_id="made_up_field"),
            _PlannedPanel(title="Unknown portfolio", group_by="sector", metric="market_value_sum", portfolio_filter=["not_a_portfolio"]),
            _PlannedPanel(title="Self pivot", kind="pivot", row_dim="sector", col_dim="sector", metric="market_value_sum"),
        ],
    )
    llm = fake_llm({"_PlannedDashboard": [planned]})

    spec, _clarification, warnings, _usage = await planner.plan_dashboard("Anything", llm, _ctx())

    assert [p.title for p in spec.panels] == ["Good"]
    assert len(warnings) == 5
    # the rejected panels are named, so an analyst sees what was attempted and why it didn't run
    assert any("industry_supersector" in w for w in warnings)
    assert any("made_up_field" in w for w in warnings)
    assert any("not_a_portfolio" in w for w in warnings)


async def test_filter_value_matching_nothing_is_rejected_not_run_as_an_empty_panel(fake_llm):
    planned = _PlannedDashboard(
        title="Typo",
        panels=[
            _PlannedPanel(title="Good filter", group_by="portfolio_id", metric="market_value_sum", security_filter={"company_id": "bmw"}),
            _PlannedPanel(title="Misspelled issuer", group_by="portfolio_id", metric="market_value_sum", security_filter={"company_id": "bwm"}),
            _PlannedPanel(title="Misspelled sector", group_by="portfolio_id", metric="market_value_sum", security_filter={"sector": "Autos"}),
        ],
    )
    llm = fake_llm({"_PlannedDashboard": [planned]})

    spec, _clarification, warnings, _usage = await planner.plan_dashboard("BMW exposure", llm, _ctx())

    # an empty result reads as "no exposure", which is a wrong answer rather
    # than a failed query -- so a value that matches nothing is dropped
    assert [p.title for p in spec.panels] == ["Good filter"]
    assert any("company_id='bwm'" in w for w in warnings)
    assert any("sector='Autos'" in w for w in warnings)


async def test_unknown_as_of_is_rejected_rather_than_silently_snapped_to_latest(fake_llm):
    planned = _PlannedDashboard(
        title="Wrong date",
        panels=[_PlannedPanel(title="Ghost snapshot", group_by="sector", metric="market_value_sum", as_of="2025-12-31")],
    )
    llm = fake_llm({"_PlannedDashboard": [planned]})

    spec, clarification, warnings, _usage = await planner.plan_dashboard("As at year end 2025", llm, _ctx())

    assert spec is None
    assert clarification
    assert any("2025-12-31" in w for w in warnings)


async def test_ambiguous_brief_asks_instead_of_inventing_panels(fake_llm):
    llm = fake_llm({"_PlannedDashboard": [_PlannedDashboard(understood=False, clarification_needed="Which portfolio?")]})

    spec, clarification, warnings, _usage = await planner.plan_dashboard("show me the risk", llm, _ctx())

    assert spec is None
    assert clarification == "Which portfolio?"
    assert warnings == []


async def test_panel_count_is_capped(fake_llm):
    panels = [_PlannedPanel(title=f"Panel {i}", group_by="sector", metric="market_value_sum") for i in range(planner.MAX_PANELS + 3)]
    llm = fake_llm({"_PlannedDashboard": [_PlannedDashboard(title="Too many", panels=panels)]})

    spec, _clarification, warnings, _usage = await planner.plan_dashboard("everything", llm, _ctx())

    assert len(spec.panels) == planner.MAX_PANELS
    assert any("kept the first" in w for w in warnings)


def test_context_exposes_only_what_exists():
    ctx = _ctx()
    assert ctx.sectors == ["Automobiles"]
    assert ctx.asset_classes == ["corporate_bond", "equity"]
    rendered = planner._render_context(ctx)
    assert "bmw: BMW AG -- Automobiles, DE" in rendered
    assert "2026-04-01" in rendered
