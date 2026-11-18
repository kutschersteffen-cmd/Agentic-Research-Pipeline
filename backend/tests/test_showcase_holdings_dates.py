"""Showcase defect 6: a table built from holdings is labelled with the dates its rows really have. Portfolios are
loaded on their own dates, so the newest date over all portfolios is not the date of every row."""
import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_portfolio_store, settings_dep
from arp.api.main import app
from arp.config import Settings
from arp.decision import sources
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, Portfolio, SecurityRef
from arp.storage.portfolio_store import PortfolioStore

OLD, NEW = "2026-10-30", "2026-10-31"


@pytest.fixture
def store(tmp_path):
    """`old_fund` was last loaded the day before `core`."""
    store = PortfolioStore(tmp_path / "pf")
    store.save_company(CompanyRef(company_id="bmw", name="BMW AG"))
    store.save_security(SecurityRef(security_id="bmw_eq", name="BMW", asset_class="equity", currency="EUR", company_id="bmw"))
    for pid, day in (("old_fund", OLD), ("core", NEW), ("core", "2026-07-31")):
        store.save_portfolio(Portfolio(portfolio_id=pid, name=pid))
        store.save_snapshot(pid, day, [Holding(
            portfolio_id=pid, security_id="bmw_eq", as_of_date=day, quantity=1, price=10, market_value=10,
            fx_rate_to_eur=1.0, market_value_eur=10)])
    return store


def test_snapshot_dataset_is_named_after_the_dates_of_its_rows(store):
    one = sources.from_portfolio_snapshot(store, portfolio_ids=["old_fund"])
    assert (one.name, one.as_of) == (f"Portfolio holdings as of {OLD}", OLD)
    both = sources.from_portfolio_snapshot(store, portfolio_ids=["old_fund", "core"])
    assert (both.name, both.as_of) == (f"Portfolio holdings as of {OLD} to {NEW}", NEW)


def test_one_date_is_labelled_as_before(store):
    latest = sources.from_portfolio_snapshot(store, portfolio_ids=["core"])
    assert (latest.name, latest.as_of) == (f"Portfolio holdings as of {NEW}", NEW)
    earlier = sources.from_portfolio_snapshot(store, as_of="2026-07-31", portfolio_ids=["core"])
    assert (earlier.name, earlier.as_of) == ("Portfolio holdings as of 2026-07-31", "2026-07-31")


def test_universe_file_is_named_after_the_dates_of_its_rows(store, tmp_path):
    settings = Settings(runs_dir=tmp_path / "runs", portfolios_dir=tmp_path / "pf")
    app.dependency_overrides.update({get_portfolio_store: lambda: store, settings_dep: lambda: settings})
    try:
        client = TestClient(app)
        both = client.post("/api/portfolio/universe", json={"portfolio_ids": ["old_fund", "core"]}).json()
        one = client.post("/api/portfolio/universe", json={"portfolio_ids": ["core"]}).json()
    finally:
        app.dependency_overrides.pop(get_portfolio_store, None)
        app.dependency_overrides.pop(settings_dep, None)
    assert both["as_of"] == NEW and both["path"].rsplit("/", 1)[-1].startswith(f"holdings_old_fund_core_{OLD}_to_{NEW}_")
    assert one["as_of"] == NEW and one["path"].rsplit("/", 1)[-1].startswith(f"holdings_core_{NEW}_")
