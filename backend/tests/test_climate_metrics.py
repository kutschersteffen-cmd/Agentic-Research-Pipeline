from arp.portfolio.climate import metrics as climate_metrics
from arp.portfolio.climate.schemas import FIELD_CARBON_INTENSITY, FIELD_EVIC, FIELD_SCOPE1, FIELD_SCOPE2
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import DataPointObservation, Holding, SecurityRef
from arp.storage.portfolio_store import PortfolioStore


def _seed_field(store, company_id, field_id, value):
    store.append_observation(
        DataPointObservation(company_id=company_id, field_id=field_id, field_name=field_id, value=value, source="internal_api", observed_at="2026-01-01")
    )


def _holding(security_id, mv):
    return Holding(portfolio_id="p1", security_id=security_id, as_of_date="2026-01-01", quantity=1, price=mv, market_value=mv, fx_rate_to_eur=1.0, market_value_eur=mv)


def test_compute_waci(tmp_path):
    store = PortfolioStore(tmp_path)
    _seed_field(store, "a", FIELD_CARBON_INTENSITY, 10.0)
    _seed_field(store, "b", FIELD_CARBON_INTENSITY, 30.0)
    securities = {
        "a_eq": SecurityRef(security_id="a_eq", name="A", asset_class="equity", currency="EUR", company_id="a"),
        "b_eq": SecurityRef(security_id="b_eq", name="B", asset_class="equity", currency="EUR", company_id="b"),
    }
    companies = {"a": CompanyRef(company_id="a", name="A"), "b": CompanyRef(company_id="b", name="B")}
    holdings = [_holding("a_eq", 75.0), _holding("b_eq", 25.0)]

    result = climate_metrics.compute_waci(store, holdings, securities, companies, as_of="2026-01-01")

    # (75*10 + 25*30) / 100 = 15.0
    assert result.rows[0].weighted_avg_value == 15.0
    assert result.rows[0].coverage_pct == 1.0


def test_compute_financed_emissions(tmp_path):
    store = PortfolioStore(tmp_path)
    _seed_field(store, "a", FIELD_EVIC, 1000.0)
    _seed_field(store, "a", FIELD_SCOPE1, 100.0)
    _seed_field(store, "a", FIELD_SCOPE2, 50.0)
    securities = {"a_eq": SecurityRef(security_id="a_eq", name="A", asset_class="equity", currency="EUR", company_id="a")}
    holdings = [_holding("a_eq", 100.0)]

    result = climate_metrics.compute_financed_emissions(store, holdings, securities, as_of="2026-01-01")

    # attribution factor = 100/1000 = 0.1; financed = 0.1 * (100+50) = 15.0
    assert result["financed_emissions_tco2e"] == 15.0
    assert result["uncovered_holding_count"] == 0
    assert result["coverage_pct"] == 1.0


def test_compute_financed_emissions_excludes_uncovered_holdings(tmp_path):
    store = PortfolioStore(tmp_path)
    securities = {"a_eq": SecurityRef(security_id="a_eq", name="A", asset_class="equity", currency="EUR", company_id="a")}
    holdings = [_holding("a_eq", 100.0)]

    result = climate_metrics.compute_financed_emissions(store, holdings, securities, as_of="2026-01-01")

    assert result["financed_emissions_tco2e"] == 0.0
    assert result["uncovered_holding_count"] == 1
    assert result["uncovered_market_value_eur"] == 100.0
    assert result["coverage_pct"] == 0.0


def test_coverage_report(tmp_path):
    store = PortfolioStore(tmp_path)
    _seed_field(store, "a", FIELD_CARBON_INTENSITY, 10.0)
    securities = {
        "a_eq": SecurityRef(security_id="a_eq", name="A", asset_class="equity", currency="EUR", company_id="a"),
        "b_eq": SecurityRef(security_id="b_eq", name="B", asset_class="equity", currency="EUR", company_id="b"),
    }
    counts = climate_metrics.coverage_report(store, securities, FIELD_CARBON_INTENSITY)
    assert counts["internal_api"] == 1
    assert counts["missing"] == 1
