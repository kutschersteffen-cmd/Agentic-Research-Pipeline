import pytest

from arp.portfolio.aggregation import aggregate, aggregate_trend, pivot
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, SecurityRef


def _security(security_id, company_id, asset_class="equity", currency="EUR"):
    return SecurityRef(security_id=security_id, isin=None, name=security_id, asset_class=asset_class, currency=currency, company_id=company_id)


def _holding(portfolio_id, security_id, as_of_date, mv_eur):
    return Holding(
        portfolio_id=portfolio_id, security_id=security_id, as_of_date=as_of_date,
        quantity=1, price=mv_eur, market_value=mv_eur, fx_rate_to_eur=1.0, market_value_eur=mv_eur,
    )


def test_market_value_sum_grouped_by_company():
    securities = {"bmw_eq": _security("bmw_eq", "bmw"), "sap_eq": _security("sap_eq", "sap")}
    companies = {
        "bmw": CompanyRef(company_id="bmw", name="BMW", sector="Automobiles", country="DE"),
        "sap": CompanyRef(company_id="sap", name="SAP", sector="Software", country="DE"),
    }
    holdings = [
        _holding("p1", "bmw_eq", "2026-01-01", 10.0),
        _holding("p2", "bmw_eq", "2026-01-01", 5.0),
        _holding("p1", "sap_eq", "2026-01-01", 20.0),
    ]
    result = aggregate(holdings, securities, companies, group_by="company_id", metric="market_value_sum", as_of="2026-01-01")
    by_group = {r.group_value: r.market_value_eur for r in result.rows}
    assert by_group == {"bmw": 15.0, "sap": 20.0}
    assert result.total_market_value_eur == 35.0


def test_security_filter_and_portfolio_filter():
    securities = {"bmw_eq": _security("bmw_eq", "bmw"), "bmw_bond": _security("bmw_bond", "bmw", asset_class="corporate_bond")}
    companies = {"bmw": CompanyRef(company_id="bmw", name="BMW")}
    holdings = [
        _holding("p1", "bmw_eq", "2026-01-01", 10.0),
        _holding("p2", "bmw_eq", "2026-01-01", 5.0),
        _holding("p1", "bmw_bond", "2026-01-01", 7.0),
    ]
    result = aggregate(
        holdings, securities, companies, group_by="portfolio_id", metric="market_value_sum", as_of="2026-01-01",
        security_filter={"asset_class": "equity"}, portfolio_filter=["p1"],
    )
    assert [r.group_value for r in result.rows] == ["p1"]
    assert result.rows[0].market_value_eur == 10.0


def test_weighted_avg_datapoint_excludes_missing_and_reports_coverage():
    securities = {"a": _security("a", "co_a"), "b": _security("b", "co_b")}
    companies = {"co_a": CompanyRef(company_id="co_a", name="A"), "co_b": CompanyRef(company_id="co_b", name="B")}
    holdings = [_holding("p1", "a", "2026-01-01", 60.0), _holding("p1", "b", "2026-01-01", 40.0)]
    result = aggregate(
        holdings, securities, companies, group_by="portfolio_id", metric="weighted_avg_datapoint", as_of="2026-01-01",
        data_point_values={"co_a": 10.0},  # co_b deliberately has no value
    )
    row = result.rows[0]
    assert row.weighted_avg_value == 10.0
    assert row.coverage_pct == 0.6
    assert result.unresolved_market_value_eur == 40.0


def test_weighted_avg_datapoint_requires_values():
    with pytest.raises(ValueError):
        aggregate([], {}, {}, group_by="portfolio_id", metric="weighted_avg_datapoint", as_of="2026-01-01")


def test_unresolved_company_groups_separately():
    securities = {"x": _security("x", None)}
    companies: dict = {}
    holdings = [_holding("p1", "x", "2026-01-01", 5.0)]
    result = aggregate(holdings, securities, companies, group_by="company_id", metric="market_value_sum", as_of="2026-01-01")
    assert result.rows[0].group_value == "(unresolved)"


def test_count_metric():
    securities = {"a": _security("a", "co_a")}
    companies = {"co_a": CompanyRef(company_id="co_a", name="A")}
    holdings = [_holding("p1", "a", "2026-01-01", 1.0), _holding("p2", "a", "2026-01-01", 2.0)]
    result = aggregate(holdings, securities, companies, group_by="company_id", metric="count", as_of="2026-01-01")
    assert result.rows[0].holding_count == 2


def test_pivot_cross_tabs_two_dimensions():
    securities = {
        "bmw_eq": _security("bmw_eq", "bmw", asset_class="equity"),
        "bmw_bond": _security("bmw_bond", "bmw", asset_class="corporate_bond"),
        "sap_eq": _security("sap_eq", "sap", asset_class="equity"),
    }
    companies = {"bmw": CompanyRef(company_id="bmw", name="BMW"), "sap": CompanyRef(company_id="sap", name="SAP")}
    holdings = [
        _holding("p1", "bmw_eq", "2026-01-01", 10.0),
        _holding("p1", "bmw_bond", "2026-01-01", 5.0),
        _holding("p1", "sap_eq", "2026-01-01", 20.0),
    ]
    result = pivot(holdings, securities, companies, row_dim="company_id", col_dim="asset_class", metric="market_value_sum", as_of="2026-01-01")

    by_cell = {(c.row_value, c.col_value): c.market_value_eur for c in result.cells}
    assert by_cell == {("bmw", "corporate_bond"): 5.0, ("bmw", "equity"): 10.0, ("sap", "equity"): 20.0}
    assert result.row_values == ["bmw", "sap"]
    assert result.col_values == ["corporate_bond", "equity"]
    # sap/corporate_bond has no holdings -- absent from cells, not a fabricated zero
    assert ("sap", "corporate_bond") not in by_cell


def test_pivot_weighted_avg_datapoint_matches_aggregate():
    securities = {"a": _security("a", "co_a"), "b": _security("b", "co_b")}
    companies = {"co_a": CompanyRef(company_id="co_a", name="A"), "co_b": CompanyRef(company_id="co_b", name="B")}
    holdings = [_holding("p1", "a", "2026-01-01", 60.0), _holding("p1", "b", "2026-01-01", 40.0)]

    agg = aggregate(
        holdings, securities, companies, group_by="portfolio_id", metric="weighted_avg_datapoint", as_of="2026-01-01",
        data_point_values={"co_a": 10.0, "co_b": 20.0},
    )
    piv = pivot(
        holdings, securities, companies, row_dim="portfolio_id", col_dim="company_id", metric="weighted_avg_datapoint", as_of="2026-01-01",
        data_point_values={"co_a": 10.0, "co_b": 20.0},
    )

    # (60*10 + 40*20) / 100 = 14.0, computed identically by both entry points
    assert agg.rows[0].weighted_avg_value == 14.0
    cell_values = {c.col_value: c.weighted_avg_value for c in piv.cells}
    assert cell_values == {"co_a": 10.0, "co_b": 20.0}


def test_pivot_requires_valid_metric():
    with pytest.raises(ValueError):
        pivot([], {}, {}, row_dim="portfolio_id", col_dim="asset_class", metric="bogus", as_of="2026-01-01")


def test_aggregate_trend_runs_per_date():
    securities = {"a": _security("a", "co_a")}
    companies = {"co_a": CompanyRef(company_id="co_a", name="A")}
    holdings_by_date = {
        "2026-01-01": [_holding("p1", "a", "2026-01-01", 10.0)],
        "2026-02-01": [_holding("p1", "a", "2026-02-01", 12.0)],
    }
    points = aggregate_trend(holdings_by_date, securities, companies, group_by="portfolio_id", metric="market_value_sum")
    assert [p.as_of for p in points] == ["2026-01-01", "2026-02-01"]
    assert points[1].result.total_market_value_eur == 12.0
