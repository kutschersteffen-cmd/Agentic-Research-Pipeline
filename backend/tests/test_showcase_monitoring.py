"""Showcase defect 5 (backend): a monitoring rule can be deleted and its live alerts cleared in one step,
without rewriting any stored alert event."""
import pytest
from fastapi.testclient import TestClient

from arp.api.auth import Principal, authorize, current_user
from arp.api.deps import get_portfolio_store
from arp.api.main import app
from arp.portfolio.monitoring.evaluator import evaluate_threshold_rules, list_alerts
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, Portfolio, SecurityRef
from arp.schemas.portfolio_monitoring import AlertRule
from arp.storage.portfolio_store import PortfolioStore

RULES = "/api/portfolio/monitoring/rules"


@pytest.fixture
def env(tmp_path):
    """A portfolio holding two companies, and a concentration rule that both breach (two open alerts)."""
    store = PortfolioStore(tmp_path)
    store.save_portfolio(Portfolio(portfolio_id="p1", name="P1"))
    for cid in ("c1", "c2"):
        store.save_company(CompanyRef(company_id=cid, name=cid.upper()))
        store.save_security(SecurityRef(security_id=f"s_{cid}", name=cid, asset_class="equity", currency="EUR", company_id=cid))
    store.save_snapshot("p1", "2026-01-01", [
        Holding(portfolio_id="p1", security_id=f"s_{cid}", as_of_date="2026-01-01", quantity=1, price=50, market_value=50, market_value_eur=50)
        for cid in ("c1", "c2")])
    rule = AlertRule(name="Any weight", rule_type="concentration_threshold", comparator="gt", threshold_value=0)
    store.save_rule(rule)
    assert len(evaluate_threshold_rules(store)) == 2
    app.dependency_overrides[get_portfolio_store] = lambda: store
    yield {"client": TestClient(app), "store": store, "rule": rule}
    app.dependency_overrides.pop(get_portfolio_store, None)


def test_clear_alerts_appends_one_status_change_per_live_alert(env):  # AC-54
    store, rule = env["store"], env["rule"]
    before = store.list_alert_events("c1")
    r = env["client"].post(f"{RULES}/{rule.rule_id}/clear-alerts", json={"status": "false_positive", "reason": "wrong threshold"})
    assert (r.status_code, r.json()) == (200, {"cleared": 2})
    events = store.list_alert_events("c1")
    assert events[: len(before)] == before and len(events) == len(before) + 1
    transition = events[-1]["transition"]
    assert events[-1]["event_type"] == "status_changed"
    assert (transition["status"], transition["reason"], transition["decided_by"]) == ("false_positive", "wrong threshold", "Test")
    assert {a.status for a in list_alerts(store)} == {"false_positive"}
    assert env["client"].post(f"{RULES}/{rule.rule_id}/clear-alerts", json={"status": "resolved"}).json() == {"cleared": 0}


def test_clear_alerts_takes_only_a_closing_status_and_leaves_other_rules_alone(env):
    store, rule = env["store"], env["rule"]
    other = AlertRule(name="Other", rule_type="concentration_threshold", comparator="gt", threshold_value=0)
    store.save_rule(other)
    evaluate_threshold_rules(store)
    assert env["client"].post(f"{RULES}/{rule.rule_id}/clear-alerts", json={"status": "acknowledged"}).status_code == 422
    assert len(list_alerts(store, status="open")) == 4
    assert env["client"].post(f"{RULES}/{rule.rule_id}/clear-alerts", json={"status": "resolved"}).json() == {"cleared": 2}
    assert [a.rule_id for a in list_alerts(store, status="open")] == [other.rule_id] * 2


def test_delete_is_refused_while_alerts_are_live_then_removes_only_the_rule(env):
    client, store, rule = env["client"], env["store"], env["rule"]
    r = client.delete(f"{RULES}/{rule.rule_id}")
    assert (r.status_code, r.json()["detail"]) == (409, "Rule has 2 live alerts: clear them first.")
    assert store.get_rule(rule.rule_id) is not None
    client.post(f"{RULES}/{rule.rule_id}/clear-alerts", json={"status": "false_positive"})
    assert client.delete(f"{RULES}/{rule.rule_id}").status_code == 204
    assert store.list_rules() == []
    assert [a.status for a in list_alerts(store)] == ["false_positive"] * 2  # the alerts outlive their rule
    r = client.delete(f"{RULES}/rule_nope")
    assert (r.status_code, r.json()["detail"]) == (404, "Unknown rule rule_nope")
    # alerts of a deleted rule can still be cleared: the route does not need the rule
    assert client.post(f"{RULES}/{rule.rule_id}/clear-alerts", json={"status": "resolved"}).json() == {"cleared": 0}


def test_viewer_may_neither_delete_nor_clear(env):  # AC-65
    app.dependency_overrides.pop(authorize, None)
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u_v", name="Vera", role="viewer")
    rule = env["rule"]
    assert env["client"].delete(f"{RULES}/{rule.rule_id}").status_code == 403
    assert env["client"].post(f"{RULES}/{rule.rule_id}/clear-alerts", json={"status": "resolved"}).status_code == 403
    assert env["store"].get_rule(rule.rule_id) is not None
    assert len(list_alerts(env["store"], status="open")) == 2
