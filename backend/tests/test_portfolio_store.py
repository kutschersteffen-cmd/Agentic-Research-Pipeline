from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import DataPointObservation, Holding, Portfolio, SecurityRef, SecurityResolution
from arp.schemas.portfolio_monitoring import AlertRule
from arp.storage.portfolio_store import PortfolioStore


def _holding(portfolio_id, security_id, as_of_date, mv=100.0):
    return Holding(
        portfolio_id=portfolio_id, security_id=security_id, as_of_date=as_of_date,
        quantity=1, price=mv, market_value=mv, fx_rate_to_eur=1.0, market_value_eur=mv,
    )


def test_snapshot_round_trip(tmp_path):
    store = PortfolioStore(tmp_path)
    store.save_snapshot("p1", "2026-01-01", [_holding("p1", "a", "2026-01-01")])
    loaded = store.load_snapshot("p1", "2026-01-01")
    assert len(loaded) == 1
    assert loaded[0].security_id == "a"


def test_latest_snapshot_date_and_load_holdings_as_of(tmp_path):
    store = PortfolioStore(tmp_path)
    store.save_portfolio(Portfolio(portfolio_id="p1", name="P1"))
    store.save_snapshot("p1", "2026-01-01", [_holding("p1", "a", "2026-01-01", 10.0)])
    store.save_snapshot("p1", "2026-02-01", [_holding("p1", "a", "2026-02-01", 20.0)])
    assert store.latest_snapshot_date("p1") == "2026-02-01"
    # A date between two snapshots picks the nearest one on/before it, not the later one.
    holdings = store.load_holdings_as_of("2026-01-15", ["p1"])
    assert holdings[0].market_value_eur == 10.0


def test_companies_and_securities_round_trip(tmp_path):
    store = PortfolioStore(tmp_path)
    store.save_company(CompanyRef(company_id="bmw", name="BMW AG"))
    store.save_security(SecurityRef(security_id="bmw_eq", name="BMW AG", asset_class="equity", currency="EUR", company_id="bmw"))
    assert store.get_company("bmw").name == "BMW AG"
    assert store.get_security("bmw_eq").company_id == "bmw"
    assert len(store.list_companies()) == 1
    assert len(store.list_securities()) == 1


def test_resolutions_needing_review(tmp_path):
    store = PortfolioStore(tmp_path)
    store.save_resolution(SecurityResolution(security_id="s1", company_id="bmw", confidence=1.0, method="isin_exact", needs_review=False))
    store.save_resolution(SecurityResolution(security_id="s2", company_id=None, confidence=0.2, method="name_fuzzy", needs_review=True))
    pending = store.list_resolutions_needing_review()
    assert [r.security_id for r in pending] == ["s2"]


def test_list_observation_keys(tmp_path):
    store = PortfolioStore(tmp_path)
    store.append_observation(DataPointObservation(company_id="bmw", field_id="f1", field_name="F1", value=1.0, source="internal_api", observed_at="2026-01-01"))
    store.append_observation(DataPointObservation(company_id="sap", field_id="f2", field_name="F2", value=2.0, source="internal_api", observed_at="2026-01-01"))
    assert store.list_observation_keys() == [("bmw", "f1"), ("sap", "f2")]


def test_list_observation_keys_empty_when_nothing_recorded(tmp_path):
    store = PortfolioStore(tmp_path)
    assert store.list_observation_keys() == []


def test_alert_rule_round_trip(tmp_path):
    store = PortfolioStore(tmp_path)
    rule = AlertRule(name="High carbon intensity", rule_type="field_threshold", field_id="climate_carbon_intensity", comparator="gt", threshold_value=400.0)
    store.save_rule(rule)
    assert store.get_rule(rule.rule_id) == rule
    assert store.list_rules() == [rule]
    assert store.list_rules(enabled_only=True) == [rule]


def test_alert_rule_list_excludes_disabled_when_enabled_only(tmp_path):
    store = PortfolioStore(tmp_path)
    store.save_rule(AlertRule(name="Disabled rule", rule_type="field_threshold", field_id="f1", comparator="gt", threshold_value=1.0, enabled=False))
    assert store.list_rules() == store.list_rules()  # sanity: doesn't raise
    assert store.list_rules(enabled_only=True) == []


def test_alert_events_append_and_list_per_scope(tmp_path):
    store = PortfolioStore(tmp_path)
    store.append_alert_event("bmw", "alert_raised", {"alert": {"alert_id": "a1"}})
    store.append_alert_event("bmw", "status_changed", {"alert_id": "a1", "transition": {"status": "resolved"}})
    store.append_alert_event("sap", "alert_raised", {"alert": {"alert_id": "a2"}})

    bmw_events = store.list_alert_events("bmw")
    assert [e["event_type"] for e in bmw_events] == ["alert_raised", "status_changed"]
    assert store.list_alert_events("sap")[0]["alert"]["alert_id"] == "a2"
    assert store.list_all_alert_scope_ids() == ["bmw", "sap"]


def test_list_all_alert_scope_ids_excludes_rules_json(tmp_path):
    store = PortfolioStore(tmp_path)
    store.save_rule(AlertRule(name="R", rule_type="field_threshold", field_id="f1", comparator="gt", threshold_value=1.0))
    store.append_alert_event("bmw", "alert_raised", {"alert": {}})
    assert store.list_all_alert_scope_ids() == ["bmw"]
