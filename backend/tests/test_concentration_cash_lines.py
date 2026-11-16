"""stewardship-decisions-round-2, area 4: a company's concentration weight sums only its non-cash lines, over a
NAV that still includes every line (AC-20 to AC-22)."""
import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_portfolio_store
from arp.api.main import app
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, Portfolio, SecurityRef
from arp.schemas.portfolio_monitoring import AlertRule
from arp.storage.portfolio_store import PortfolioStore

SECURITIES = (("C1EQ", "equity", "C1"), ("C1CASH", "cash", "C1"), ("OTHER", "equity", "OTHER"),
              ("_CURRENCYUSD", "other", "C2"))


@pytest.fixture
def evaluate(tmp_path):
    store = PortfolioStore(tmp_path)
    for sid, cls, cid in SECURITIES:
        store.save_company(CompanyRef(company_id=cid, name=cid))
        store.save_security(SecurityRef(security_id=sid, name=sid, asset_class=cls, currency="EUR", company_id=cid))
    store.save_portfolio(Portfolio(portfolio_id="p1", name="P1"))
    store.save_rule(AlertRule(name="above 6%", rule_type="concentration_threshold", comparator="gt", threshold_value=0.06))
    app.dependency_overrides[get_portfolio_store] = lambda: store

    def run(lines: dict[str, float]) -> dict[str, float]:
        assert sum(lines.values()) == 1000  # NAV
        store.save_snapshot("p1", "2026-11-02", [
            Holding(portfolio_id="p1", security_id=sid, as_of_date="2026-11-02", quantity=1, price=mv, market_value=mv,
                    market_value_eur=mv) for sid, mv in lines.items()])
        client = TestClient(app)
        assert client.post("/api/portfolio/monitoring/evaluate-now").status_code == 200
        return {a["company_id"]: a["observed_value"] for a in client.get("/api/portfolio/monitoring/alerts").json()}

    yield run
    app.dependency_overrides.pop(get_portfolio_store, None)


def test_cash_line_left_out_of_company_weight(evaluate):  # AC-20: 50 / 1000 = 5.00 %, not (50 + 30) / 1000
    assert "C1" not in evaluate({"C1EQ": 50, "C1CASH": 30, "OTHER": 920})


def test_non_cash_weight_over_full_nav_alerts(evaluate):  # AC-21
    assert evaluate({"C1EQ": 70, "C1CASH": 30, "OTHER": 900})["C1"] == 0.07


def test_currency_only_company_never_alerts(evaluate):  # AC-22
    assert "C2" not in evaluate({"C1EQ": 50, "C1CASH": 30, "_CURRENCYUSD": 200, "OTHER": 720})
