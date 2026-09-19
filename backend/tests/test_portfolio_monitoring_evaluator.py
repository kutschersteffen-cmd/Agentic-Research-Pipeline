from __future__ import annotations

from arp.portfolio.monitoring.evaluator import evaluate_news_triggers, evaluate_threshold_rules, list_alerts, transition_alert
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, NewsRiskFlag, Portfolio, SecurityRef
from arp.schemas.portfolio_monitoring import AlertRule, AlertStatus, AlertTransition, BreachType
from arp.storage.portfolio_store import PortfolioStore


def _seed_single_holding(store: PortfolioStore, *, as_of_date: str = "2026-01-01", market_value: float = 100.0) -> None:
    store.save_portfolio(Portfolio(portfolio_id="p1", name="Test Portfolio"))
    store.save_company(CompanyRef(company_id="c1", name="Acme Corp"))
    store.save_security(SecurityRef(security_id="s1", name="Acme Corp", asset_class="equity", currency="EUR", company_id="c1"))
    store.save_snapshot(
        "p1", as_of_date,
        [Holding(portfolio_id="p1", security_id="s1", as_of_date=as_of_date, quantity=1, price=market_value, market_value=market_value, market_value_eur=market_value)],
    )


def _field_rule(**overrides) -> AlertRule:
    defaults = {"name": "High carbon intensity", "rule_type": "field_threshold", "field_id": "climate_carbon_intensity", "comparator": "gt", "threshold_value": 400.0}
    return AlertRule(**{**defaults, **overrides})


# --- dedup ---


def test_evaluate_threshold_rules_opens_alert_for_new_breach(tmp_path):
    from arp.schemas.portfolio import DataPointObservation

    store = PortfolioStore(tmp_path)
    _seed_single_holding(store)
    store.append_observation(DataPointObservation(company_id="c1", field_id="climate_carbon_intensity", field_name="CI", value=500.0, source="internal_api"))
    store.save_rule(_field_rule())

    alerts = evaluate_threshold_rules(store)

    assert len(alerts) == 1
    assert alerts[0].company_id == "c1"
    assert alerts[0].status == AlertStatus.OPEN


def test_evaluate_threshold_rules_dedupes_against_open_alert(tmp_path):
    from arp.schemas.portfolio import DataPointObservation

    store = PortfolioStore(tmp_path)
    _seed_single_holding(store)
    store.append_observation(DataPointObservation(company_id="c1", field_id="climate_carbon_intensity", field_name="CI", value=500.0, source="internal_api"))
    store.save_rule(_field_rule())

    evaluate_threshold_rules(store)
    second_pass = evaluate_threshold_rules(store)

    assert second_pass == []
    assert len(list_alerts(store)) == 1


def test_evaluate_threshold_rules_reopens_after_resolution(tmp_path):
    from arp.schemas.portfolio import DataPointObservation

    store = PortfolioStore(tmp_path)
    _seed_single_holding(store)
    store.append_observation(DataPointObservation(company_id="c1", field_id="climate_carbon_intensity", field_name="CI", value=500.0, source="internal_api"))
    store.save_rule(_field_rule())

    first = evaluate_threshold_rules(store)
    transition_alert(store, first[0].scope_id, first[0].alert_id, AlertTransition(status=AlertStatus.RESOLVED, decided_by="jane.pm"))
    reopened = evaluate_threshold_rules(store)

    assert len(reopened) == 1
    assert len(list_alerts(store)) == 2


def test_evaluate_threshold_rules_no_alert_when_disabled(tmp_path):
    from arp.schemas.portfolio import DataPointObservation

    store = PortfolioStore(tmp_path)
    _seed_single_holding(store)
    store.append_observation(DataPointObservation(company_id="c1", field_id="climate_carbon_intensity", field_name="CI", value=500.0, source="internal_api"))
    store.save_rule(_field_rule(enabled=False))

    assert evaluate_threshold_rules(store) == []


def test_evaluate_threshold_rules_no_alert_when_below_threshold(tmp_path):
    from arp.schemas.portfolio import DataPointObservation

    store = PortfolioStore(tmp_path)
    _seed_single_holding(store)
    store.append_observation(DataPointObservation(company_id="c1", field_id="climate_carbon_intensity", field_name="CI", value=100.0, source="internal_api"))
    store.save_rule(_field_rule())

    assert evaluate_threshold_rules(store) == []


# --- drift classification ---


def test_field_threshold_breach_is_always_data_caused(tmp_path):
    from arp.schemas.portfolio import DataPointObservation

    store = PortfolioStore(tmp_path)
    _seed_single_holding(store)
    store.append_observation(DataPointObservation(company_id="c1", field_id="climate_carbon_intensity", field_name="CI", value=500.0, source="internal_api"))
    store.save_rule(_field_rule())

    alerts = evaluate_threshold_rules(store)

    assert alerts[0].breach_type == BreachType.DATA_CAUSED


def test_concentration_breach_is_always_holdings_caused(tmp_path):
    store = PortfolioStore(tmp_path)
    _seed_single_holding(store)  # the only holding -> 100% concentration
    store.save_rule(AlertRule(name="Concentration limit", rule_type="concentration_threshold", comparator="gt", threshold_value=0.5))

    alerts = evaluate_threshold_rules(store)

    assert len(alerts) == 1
    assert alerts[0].breach_type == BreachType.HOLDINGS_CAUSED


def test_waci_breach_first_ever_is_unknown(tmp_path):
    from arp.schemas.portfolio import DataPointObservation

    store = PortfolioStore(tmp_path)
    _seed_single_holding(store)
    store.append_observation(
        DataPointObservation(company_id="c1", field_id="climate_carbon_intensity", field_name="CI", value=500.0, source="internal_api", observed_at="2025-06-01T00:00:00+00:00")
    )
    store.save_rule(AlertRule(name="WACI limit", rule_type="portfolio_aggregate_threshold", field_id="climate_carbon_intensity", comparator="gt", threshold_value=50.0))

    alerts = evaluate_threshold_rules(store, as_of="2026-01-01")

    assert len(alerts) == 1
    assert alerts[0].breach_type == BreachType.UNKNOWN


def test_waci_breach_classified_holdings_caused_when_snapshot_changes_data_unchanged(tmp_path):
    from arp.schemas.portfolio import DataPointObservation

    store = PortfolioStore(tmp_path)
    _seed_single_holding(store, as_of_date="2026-01-01")
    store.append_observation(
        DataPointObservation(company_id="c1", field_id="climate_carbon_intensity", field_name="CI", value=500.0, source="internal_api", observed_at="2025-06-01T00:00:00+00:00")
    )
    rule = AlertRule(name="WACI limit", rule_type="portfolio_aggregate_threshold", field_id="climate_carbon_intensity", comparator="gt", threshold_value=50.0)
    store.save_rule(rule)

    first = evaluate_threshold_rules(store, as_of="2026-01-01")
    transition_alert(store, first[0].scope_id, first[0].alert_id, AlertTransition(status=AlertStatus.RESOLVED, decided_by="jane.pm"))

    # New snapshot (a trade/price move), same resolved climate data.
    store.save_snapshot("p1", "2026-02-01", [Holding(portfolio_id="p1", security_id="s1", as_of_date="2026-02-01", quantity=2, price=100, market_value=200, market_value_eur=200)])
    second = evaluate_threshold_rules(store, as_of="2026-02-01")

    assert second[0].breach_type == BreachType.HOLDINGS_CAUSED


def test_waci_breach_classified_data_caused_when_observation_restated_snapshot_unchanged(tmp_path):
    """The spec's own literal example: 'a portfolio can breach a limit not
    because anything was traded, but because a name's rating or emissions
    data was restated'."""
    from arp.schemas.portfolio import DataPointObservation

    store = PortfolioStore(tmp_path)
    _seed_single_holding(store, as_of_date="2026-01-01")
    store.append_observation(
        DataPointObservation(company_id="c1", field_id="climate_carbon_intensity", field_name="CI", value=500.0, source="internal_api", observed_at="2025-06-01T00:00:00+00:00")
    )
    rule = AlertRule(name="WACI limit", rule_type="portfolio_aggregate_threshold", field_id="climate_carbon_intensity", comparator="gt", threshold_value=50.0)
    store.save_rule(rule)

    first = evaluate_threshold_rules(store, as_of="2026-01-01")
    transition_alert(store, first[0].scope_id, first[0].alert_id, AlertTransition(status=AlertStatus.RESOLVED, decided_by="jane.pm"))

    # No trade, no new snapshot -- just a restated (higher) emissions figure.
    store.append_observation(
        DataPointObservation(company_id="c1", field_id="climate_carbon_intensity", field_name="CI", value=900.0, source="internal_api", observed_at="2025-06-02T00:00:00+00:00")
    )
    second = evaluate_threshold_rules(store, as_of="2026-01-01")

    assert second[0].breach_type == BreachType.DATA_CAUSED


def test_waci_breach_classified_mixed_when_both_change(tmp_path):
    from arp.schemas.portfolio import DataPointObservation

    store = PortfolioStore(tmp_path)
    _seed_single_holding(store, as_of_date="2026-01-01")
    store.append_observation(
        DataPointObservation(company_id="c1", field_id="climate_carbon_intensity", field_name="CI", value=500.0, source="internal_api", observed_at="2025-06-01T00:00:00+00:00")
    )
    rule = AlertRule(name="WACI limit", rule_type="portfolio_aggregate_threshold", field_id="climate_carbon_intensity", comparator="gt", threshold_value=50.0)
    store.save_rule(rule)

    first = evaluate_threshold_rules(store, as_of="2026-01-01")
    transition_alert(store, first[0].scope_id, first[0].alert_id, AlertTransition(status=AlertStatus.RESOLVED, decided_by="jane.pm"))

    store.append_observation(
        DataPointObservation(company_id="c1", field_id="climate_carbon_intensity", field_name="CI", value=900.0, source="internal_api", observed_at="2026-01-15T00:00:00+00:00")
    )
    store.save_snapshot("p1", "2026-02-01", [Holding(portfolio_id="p1", security_id="s1", as_of_date="2026-02-01", quantity=2, price=100, market_value=200, market_value_eur=200)])
    second = evaluate_threshold_rules(store, as_of="2026-02-01")

    assert second[0].breach_type == BreachType.MIXED


# --- news triggers ---


def test_evaluate_news_triggers_creates_alert_for_high_severity_flag(tmp_path):
    store = PortfolioStore(tmp_path)
    store.append_flag(NewsRiskFlag(news_id="n1", company_id="c1", category="climate_controversy", severity="high", rationale="Spill reported", quote="spill"))

    [flag] = store.list_flags()
    alerts = evaluate_news_triggers(store, min_severity="medium")

    assert len(alerts) == 1
    assert alerts[0].source_flag_id == flag.flag_id
    assert alerts[0].company_id == "c1"


def test_evaluate_news_triggers_skips_below_min_severity(tmp_path):
    store = PortfolioStore(tmp_path)
    store.append_flag(NewsRiskFlag(news_id="n1", company_id="c1", category="other", severity="low", rationale="Minor note", quote="minor"))

    assert evaluate_news_triggers(store, min_severity="medium") == []


def test_evaluate_news_triggers_dedupes_already_alerted_flag_id(tmp_path):
    store = PortfolioStore(tmp_path)
    store.append_flag(NewsRiskFlag(news_id="n1", company_id="c1", category="climate_controversy", severity="high", rationale="Spill reported", quote="spill"))

    first = evaluate_news_triggers(store, min_severity="medium")
    transition_alert(store, first[0].scope_id, first[0].alert_id, AlertTransition(status=AlertStatus.RESOLVED, decided_by="jane.pm"))
    second = evaluate_news_triggers(store, min_severity="medium")

    assert second == []  # unlike a threshold breach, a resolved news alert never re-fires
