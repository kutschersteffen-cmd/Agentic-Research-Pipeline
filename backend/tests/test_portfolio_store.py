from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, Portfolio, SecurityRef, SecurityResolution
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
