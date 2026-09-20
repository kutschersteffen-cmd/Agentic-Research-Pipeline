from arp.portfolio.genbi import observations
from arp.portfolio.genbi.schemas import PanelSpec
from arp.schemas.portfolio import AggregationResult, AggregationRow, NewsRiskFlag, PivotCell, PivotResult, TrendPoint


def _panel(**kwargs) -> PanelSpec:
    return PanelSpec(title="Panel", group_by="sector", **kwargs)


def _result(rows, metric="market_value_sum", total=None, unresolved=0.0, group_by="sector"):
    return AggregationResult(
        spec_name="Panel",
        as_of="2026-04-01",
        metric=metric,
        group_by=group_by,
        rows=rows,
        total_market_value_eur=total if total is not None else sum(r.market_value_eur or 0 for r in rows),
        unresolved_market_value_eur=unresolved,
    )


def test_aggregation_facts_cover_total_leader_and_concentration():
    rows = [
        AggregationRow(group_value="Energy", market_value_eur=500_000, holding_count=3),
        AggregationRow(group_value="Autos", market_value_eur=300_000, holding_count=2),
        AggregationRow(group_value="Banks", market_value_eur=150_000, holding_count=2),
        AggregationRow(group_value="Utilities", market_value_eur=50_000, holding_count=1),
    ]
    facts = observations.facts_for_aggregation(_panel(), _result(rows))
    by_kind = {f.kind: f for f in facts}

    assert by_kind["total"].value == 1_000_000
    assert "8 holdings" in by_kind["total"].text
    assert by_kind["top_contributor"].value == 500_000
    assert "50.0% of the EUR 1,000,000 total" in by_kind["top_contributor"].text
    assert by_kind["concentration"].value == 0.95
    assert "95.0%" in by_kind["concentration"].text


def test_concentration_fact_is_skipped_when_it_would_just_restate_the_total():
    rows = [
        AggregationRow(group_value="Energy", market_value_eur=500_000, holding_count=1),
        AggregationRow(group_value="Autos", market_value_eur=300_000, holding_count=1),
        AggregationRow(group_value="Banks", market_value_eur=200_000, holding_count=1),
    ]
    facts = observations.facts_for_aggregation(_panel(), _result(rows))
    assert not [f for f in facts if f.kind == "concentration"]


def test_weighted_average_facts_report_coverage_and_exclusions():
    rows = [
        AggregationRow(group_value="Energy", market_value_eur=600_000, weighted_avg_value=310.0, coverage_pct=1.0, holding_count=2),
        AggregationRow(group_value="Autos", market_value_eur=400_000, weighted_avg_value=95.5, coverage_pct=0.5, holding_count=2),
    ]
    result = _result(rows, metric="weighted_avg_datapoint", total=1_000_000, unresolved=200_000)
    facts = observations.facts_for_aggregation(
        _panel(metric="weighted_avg_datapoint", data_point_field_id="climate_carbon_intensity"), result, unit="tCO2e / EUR M revenue"
    )
    by_kind = {f.kind: f for f in facts}
    by_label = {f.label: f for f in facts}

    assert by_kind["top_contributor"].text.startswith("Highest sector: Energy at 310.00 tCO2e")
    assert by_label["Data-point coverage"].value == 0.8
    # partial coverage is stated, and the excluded market value is never folded in as zero
    assert "80.0%" in by_label["Data-point coverage"].text
    assert by_kind["unresolved"].value == 200_000
    assert "not counted as zero" in by_kind["unresolved"].text
    assert any("Weakest coverage by sector: Autos at 50.0%" in f.text for f in facts)


def test_trend_facts_compare_first_and_last_snapshot():
    trend = [
        TrendPoint(as_of="2026-01-01", result=_result([AggregationRow(group_value="Energy", market_value_eur=400_000, holding_count=1), AggregationRow(group_value="Autos", market_value_eur=600_000, holding_count=1)])),
        TrendPoint(as_of="2026-04-01", result=_result([AggregationRow(group_value="Energy", market_value_eur=700_000, holding_count=1), AggregationRow(group_value="Autos", market_value_eur=500_000, holding_count=1)])),
    ]
    facts = observations.facts_for_trend(_panel(kind="trend"), trend)
    by_kind = {f.kind: f for f in facts}

    assert by_kind["trend_delta"].value == 200_000
    assert "rose from EUR 1,000,000 (2026-01-01) to EUR 1,200,000 (2026-04-01)" in by_kind["trend_delta"].text
    assert by_kind["trend_mover"].value == 300_000
    assert "Energy increased by EUR 300,000" in by_kind["trend_mover"].text


def test_single_snapshot_trend_yields_no_movement_claim():
    trend = [TrendPoint(as_of="2026-01-01", result=_result([AggregationRow(group_value="Energy", market_value_eur=1.0, holding_count=1)]))]
    assert observations.facts_for_trend(_panel(kind="trend"), trend) == []


def test_pivot_facts_name_largest_cell_and_row_total():
    pivot = PivotResult(
        spec_name="Panel",
        as_of="2026-04-01",
        metric="market_value_sum",
        row_dim="sector",
        col_dim="portfolio_id",
        row_values=["Energy", "Autos"],
        col_values=["p1", "p2"],
        cells=[
            PivotCell(row_value="Energy", col_value="p1", market_value_eur=300_000, holding_count=1),
            PivotCell(row_value="Energy", col_value="p2", market_value_eur=200_000, holding_count=1),
            PivotCell(row_value="Autos", col_value="p1", market_value_eur=400_000, holding_count=1),
            PivotCell(row_value="Autos", col_value="p2", market_value_eur=100_000, holding_count=1),
        ],
        total_market_value_eur=1_000_000,
    )
    facts = observations.facts_for_pivot(_panel(kind="pivot"), pivot)
    by_kind = {f.kind: f for f in facts}

    assert by_kind["largest_cell"].value == 400_000
    assert "Autos / p1" in by_kind["largest_cell"].text
    assert by_kind["row_total"].value == 500_000
    assert "Energy at EUR 500,000, 50.0%" in by_kind["row_total"].text


def test_only_grounded_news_flags_become_facts():
    flags = [
        NewsRiskFlag(news_id="n1", company_id="bmw", category="climate_controversy", severity="high", rationale="r", quote="q", grounded=True),
        NewsRiskFlag(news_id="n2", company_id="total", category="litigation", severity="low", rationale="r", quote="q", grounded=True),
        NewsRiskFlag(news_id="n3", company_id="shell", category="regulatory", severity="high", rationale="r", quote="not in source", grounded=False),
    ]
    facts = observations.facts_for_news_flags(flags)

    assert len(facts) == 1
    assert facts[0].value == 2
    assert "2 grounded news risk flag(s) across 2 issuer(s)" in facts[0].text
    assert "1 rated high severity" in facts[0].text
    assert "shell" not in facts[0].text
    assert observations.facts_for_news_flags([f for f in flags if not f.grounded]) == []
