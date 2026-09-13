import pytest

from arp.portfolio.genbi import service
from arp.portfolio.genbi.executor import execute_panel
from arp.portfolio.genbi.narrator import _NarrativeDraft, _PanelNote
from arp.portfolio.genbi.planner import _PlannedDashboard, _PlannedPanel
from arp.portfolio.genbi.schemas import DashboardSpec, PanelSpec
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import DataPointObservation, Holding, Portfolio, SecurityRef
from arp.storage.portfolio_store import PortfolioStore

DATES = ["2026-01-01", "2026-04-01"]


def _store(tmp_path) -> PortfolioStore:
    store = PortfolioStore(tmp_path)
    store.save_portfolio(Portfolio(portfolio_id="p1", name="Core Equity"))
    store.save_portfolio(Portfolio(portfolio_id="p2", name="Bond Income"))
    for company_id, name, sector in [("bmw", "BMW AG", "Automobiles"), ("total", "TotalEnergies SE", "Energy")]:
        store.save_company(CompanyRef(company_id=company_id, name=name, sector=sector, country="DE"))
    store.save_security(SecurityRef(security_id="bmw_eq", name="BMW ord", asset_class="equity", currency="EUR", company_id="bmw"))
    store.save_security(SecurityRef(security_id="tte_eq", name="TotalEnergies ord", asset_class="equity", currency="EUR", company_id="total"))

    values = {"2026-01-01": {"bmw_eq": 400_000.0, "tte_eq": 600_000.0}, "2026-04-01": {"bmw_eq": 500_000.0, "tte_eq": 900_000.0}}
    for date, per_security in values.items():
        store.save_snapshot(
            "p1",
            date,
            [
                Holding(portfolio_id="p1", security_id=sid, as_of_date=date, quantity=1, price=mv, market_value=mv, fx_rate_to_eur=1.0, market_value_eur=mv)
                for sid, mv in per_security.items()
            ],
        )
    for company_id, intensity in [("bmw", 120.0), ("total", 380.0)]:
        store.append_observation(
            DataPointObservation(
                company_id=company_id, field_id="climate_carbon_intensity", field_name="Carbon intensity",
                value=intensity, unit="tCO2e / EUR M revenue", source="internal_api", observed_at="2026-01-02T00:00:00Z",
            )
        )
    return store


def _directories(store):
    return {s.security_id: s for s in store.list_securities()}, {c.company_id: c for c in store.list_companies()}


def test_execute_panel_uses_the_deterministic_engine(tmp_path):
    store = _store(tmp_path)
    securities, companies = _directories(store)

    result = execute_panel(PanelSpec(title="By sector", group_by="sector", metric="market_value_sum"), store, securities, companies)

    assert result.error == ""
    assert result.as_of == "2026-04-01"  # latest snapshot, not the planner's guess
    assert result.aggregation.total_market_value_eur == 1_400_000
    assert {r.group_value: r.market_value_eur for r in result.aggregation.rows} == {"Energy": 900_000, "Automobiles": 500_000}
    assert any("EUR 1,400,000" in f.text for f in result.facts)


def test_trend_panel_produces_movement_facts(tmp_path):
    store = _store(tmp_path)
    securities, companies = _directories(store)

    result = execute_panel(
        PanelSpec(title="Trend", kind="trend", group_by="sector", metric="market_value_sum", date_range=(DATES[0], DATES[1]), chart="line"),
        store, securities, companies,
    )

    assert len(result.trend) == 2
    assert any(f.kind == "trend_delta" and f.value == 400_000 for f in result.facts)


def test_weighted_datapoint_panel_reports_a_real_weighted_average(tmp_path):
    store = _store(tmp_path)
    securities, companies = _directories(store)

    result = execute_panel(
        PanelSpec(title="WACI", group_by="portfolio_id", metric="weighted_avg_datapoint", data_point_field_id="climate_carbon_intensity"),
        store, securities, companies,
    )

    # (500,000 * 120 + 900,000 * 380) / 1,400,000
    assert result.aggregation.rows[0].weighted_avg_value == pytest.approx(287.1429, abs=1e-3)
    assert any("tCO2e / EUR M revenue" in f.text for f in result.facts)


def test_failing_panel_is_isolated_not_fatal(tmp_path):
    store = _store(tmp_path)
    securities, companies = _directories(store)

    result = execute_panel(
        PanelSpec(title="Broken", group_by="sector", metric="weighted_avg_datapoint", data_point_field_id=None), store, securities, companies
    )

    assert result.error
    assert result.aggregation is None


async def test_generate_dashboard_end_to_end(tmp_path, fake_llm):
    store = _store(tmp_path)
    planned = _PlannedDashboard(
        title="Climate exposure review",
        goal="Where emissions-intensive exposure sits",
        panels=[
            _PlannedPanel(title="Exposure by sector", question="Which sectors?", group_by="sector", metric="market_value_sum"),
            _PlannedPanel(title="Carbon intensity", question="How intense?", group_by="portfolio_id", metric="weighted_avg_datapoint", data_point_field_id="climate_carbon_intensity"),
            _PlannedPanel(title="Nonsense", group_by="mood", metric="market_value_sum"),
        ],
    )
    draft = _NarrativeDraft(
        headline="Total market value in scope is EUR 1,400,000 across 2 holdings.",
        panel_notes=[_PanelNote(panel_id="ignored", text="")],
    )
    llm = fake_llm({"_PlannedDashboard": [planned], "_NarrativeDraft": [draft]})

    dashboard, usage = await service.generate_dashboard("Show me climate exposure", llm, store, save=True)

    assert dashboard.clarification_needed == ""
    assert [p.panel.title for p in dashboard.panels] == ["Exposure by sector", "Carbon intensity"]
    assert any("mood" in w for w in dashboard.warnings)
    assert dashboard.as_of == "2026-04-01"
    assert dashboard.headline.grounded and dashboard.headline.source == "llm"
    assert usage.input_tokens > 0
    # the plan is what persists -- not the prose, not the figures it described
    saved = service.list_dashboards(store)
    assert len(saved) == 1 and saved[0].title == "Climate exposure review"
    assert "headline" not in store.get_dashboard(saved[0].dashboard_id)


async def test_generate_dashboard_surfaces_clarification_without_inventing_panels(tmp_path, fake_llm):
    store = _store(tmp_path)
    llm = fake_llm({"_PlannedDashboard": [_PlannedDashboard(understood=False, clarification_needed="Which portfolio?")]})

    dashboard, _usage = await service.generate_dashboard("show me risk", llm, store)

    assert dashboard.clarification_needed == "Which portfolio?"
    assert dashboard.panels == []
    assert dashboard.headline.text == ""


def test_saved_dashboard_reruns_with_no_llm_at_all(tmp_path):
    store = _store(tmp_path)
    spec = DashboardSpec(
        title="Quarterly exposure",
        panels=[PanelSpec(title="By sector", group_by="sector", metric="market_value_sum")],
    )
    service.save_dashboard(store, spec)

    reloaded = service.get_dashboard(store, spec.dashboard_id)
    dashboard = service.run_dashboard(reloaded, store)

    assert dashboard.panels[0].aggregation.total_market_value_eur == 1_400_000
    assert dashboard.headline.source == "deterministic_fallback"
    assert dashboard.headline.grounded is True

    # and the same definition re-pointed at an earlier snapshot recomputes, never replays
    earlier = service.run_dashboard(reloaded, store, as_of="2026-01-01")
    assert earlier.panels[0].aggregation.as_of == "2026-01-01"
    assert earlier.panels[0].aggregation.total_market_value_eur == 1_000_000


def test_as_of_override_leaves_trend_panels_alone(tmp_path):
    store = _store(tmp_path)
    spec = DashboardSpec(
        title="Mixed",
        panels=[
            PanelSpec(title="Trend", kind="trend", group_by="sector", metric="market_value_sum", date_range=(DATES[0], DATES[1]), chart="line"),
            PanelSpec(title="Point", group_by="sector", metric="market_value_sum"),
        ],
    )
    dashboard = service.run_dashboard(spec, store, as_of="2026-01-01")

    assert len(dashboard.panels[0].trend) == 2
    assert dashboard.panels[1].aggregation.as_of == "2026-01-01"
