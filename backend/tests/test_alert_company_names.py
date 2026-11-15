"""showcase-alerts-company-names: alerts carry the company name, old rationales are named on read, and cash
or currency lines never raise a concentration alert while staying in the NAV total."""
import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_portfolio_store
from arp.api.main import app
from arp.portfolio.monitoring.evaluator import evaluate_threshold_rules
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, Portfolio, SecurityRef
from arp.schemas.portfolio_monitoring import Alert, AlertCategory, AlertRule, BreachType
from arp.storage.portfolio_store import PortfolioStore

ALERTS = "/api/portfolio/monitoring/alerts"
DB = "isin_DE0005140008"
OLD = f"Single name > 0.5%: {DB} = 60.00% of NAV gt 0.50%"
NEW = "Single name > 0.5%: DEUTSCHE BANK AG = 60.00% of NAV gt 0.50%"


@pytest.fixture
def env(tmp_path):
    store = PortfolioStore(tmp_path)
    for cid, name in ((DB, "DEUTSCHE BANK AG"), ("isin__CURRENCYUSD", "US Dollar"), ("cash_eur", "Euro Cash")):
        store.save_company(CompanyRef(company_id=cid, name=name))
    for sid, cls, cid in (("DE0005140008", "equity", DB), ("_CURRENCYUSD", "other", "isin__CURRENCYUSD"), ("CASHEUR", "cash", "cash_eur")):
        store.save_security(SecurityRef(security_id=sid, name=sid, asset_class=cls, currency="EUR", company_id=cid))
    store.save_portfolio(Portfolio(portfolio_id="p1", name="Core Equity Europe"))
    store.save_snapshot("p1", "2026-11-02", [
        Holding(portfolio_id="p1", security_id=sid, as_of_date="2026-11-02", quantity=1, price=mv, market_value=mv, market_value_eur=mv)
        for sid, mv in (("DE0005140008", 600_000), ("_CURRENCYUSD", 300_000), ("CASHEUR", 100_000))])
    rule = AlertRule(name="Single name > 0.5%", rule_type="concentration_threshold", comparator="gt", threshold_value=0.005)
    store.save_rule(rule)
    app.dependency_overrides[get_portfolio_store] = lambda: store
    yield {"client": TestClient(app), "store": store, "rule": rule}
    app.dependency_overrides.pop(get_portfolio_store, None)


def _store_old(store, rule, company_id, rationale, breach_type=BreachType.HOLDINGS_CAUSED, rule_id=None):
    alert = Alert(rule_id=rule_id or rule.rule_id, category=AlertCategory.THRESHOLD_BREACH, scope_id=company_id,
                  company_id=company_id, breach_type=breach_type, rationale=rationale)
    store.append_alert_event(company_id, "alert_raised", {"alert": alert.model_dump(mode="json", exclude={"company_name"})})


def test_new_alert_names_company_and_skips_cash(env):  # AC-1..AC-5
    evaluate_threshold_rules(env["store"])
    alerts = env["client"].get(ALERTS).json()
    assert [(a["company_id"], a["company_name"], a["rationale"], a["observed_value"]) for a in alerts] == [
        (DB, "DEUTSCHE BANK AG", NEW, 0.6)]
    assert "company_name" not in env["store"].list_alert_events(DB)[0]["alert"]


def test_old_rationale_is_named_on_read_and_store_untouched(env):  # AC-6..AC-8
    _store_old(env["store"], env["rule"], DB, OLD)
    [alert] = env["client"].get(ALERTS).json()
    assert (alert["company_name"], alert["rationale"]) == ("DEUTSCHE BANK AG", NEW)
    assert env["store"].list_alert_events(DB)[0]["alert"]["rationale"] == OLD


def test_unknown_company_reads_as_today(env):  # AC-9, AC-10
    old = "Single name > 0.5%: isin_XX0000000000 = 7.00% of NAV gt 0.50%"
    _store_old(env["store"], env["rule"], "isin_XX0000000000", old)
    [alert] = env["client"].get(ALERTS).json()
    assert (alert["company_name"], alert["rationale"]) == (None, old)


def test_field_threshold_gets_name_but_rationale_kept(env):  # AC-11, AC-12
    text = "Carbon cap: climate_carbon_intensity = 80 gt 50"
    _store_old(env["store"], env["rule"], DB, text, BreachType.DATA_CAUSED, rule_id="rule_carbon")
    [alert] = env["client"].get(ALERTS).json()
    assert (alert["company_name"], alert["rationale"]) == ("DEUTSCHE BANK AG", text)


def test_company_with_cash_and_equity_lines_still_alerts(env):
    store = env["store"]
    store.save_security(SecurityRef(security_id="DBCASH", name="DBCASH", asset_class="cash", currency="EUR", company_id=DB))
    store.save_snapshot("p1", "2026-11-03", [
        Holding(portfolio_id="p1", security_id=sid, as_of_date="2026-11-03", quantity=1, price=mv, market_value=mv, market_value_eur=mv)
        for sid, mv in (("DE0005140008", 10), ("DBCASH", 10), ("CASHEUR", 80))])
    assert [a.company_id for a in evaluate_threshold_rules(store, as_of="2026-11-03")] == [DB]
