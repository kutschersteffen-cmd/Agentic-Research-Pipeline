"""One set of assertions run against BOTH portfolio store backends.

Every test in this module is parametrized over the file-based
`PortfolioStore` and the opt-in `PostgresPortfolioStore`, so a behavioural
divergence between them fails a test instead of silently changing what a
number means. That is the gap that let `load_holdings_as_of` mean "latest
snapshot on or before this date" in one store and "this exact date" in
the other: both stores had tests, neither had *the same* test.

Without ARP_TEST_POSTGRES_DSN set, the Postgres half is skipped and the
file half still runs -- so this suite is useful in the default
network/database-free configuration too (see conftest.py's philosophy),
and covers both backends in CI wherever a scratch database is available:

    createdb arp_test && psql arp_test -c "CREATE EXTENSION vector;"
    ARP_TEST_POSTGRES_DSN=postgresql+psycopg://postgres@localhost:5432/arp_test pytest tests/test_portfolio_store_parity.py
"""

from __future__ import annotations

import os

import pytest

from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, Portfolio, SecurityRef, SecurityResolution
from arp.storage.portfolio_store import PortfolioStore
from tests.postgres_helpers import reset_postgres_tables

DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")

# Public methods the Postgres backend deliberately does not have: the
# filesystem-location accessors for the four concerns it relationalizes.
# There is no file behind them there, and handing back the wrapped file
# store's (empty, nonexistent) path would be worse than not offering the
# method. Every OTHER public method must exist on both stores -- including
# the *_path() accessors for concerns that stay file-backed, which the
# Postgres store delegates. Adding a method to PortfolioStore without
# either implementing or classifying it here fails
# test_public_surfaces_match.
FILE_ONLY_METHODS = frozenset(
    {"registry_path", "securities_path", "companies_path", "resolutions_path", "snapshot_path"}
)


def _file_store(tmp_path) -> PortfolioStore:
    return PortfolioStore(tmp_path / "files")


def _postgres_store(tmp_path):
    """A store on an *empty* scratch database: several assertions below are
    unfiltered ("every portfolio at this date"), so a row left behind by
    another suite would change their totals. See tests/postgres_helpers.py."""
    from arp.storage.postgres import ensure_schema
    from arp.storage.postgres_portfolio_store import PostgresPortfolioStore

    ensure_schema(DSN)
    reset_postgres_tables(DSN)
    return PostgresPortfolioStore(DSN, PortfolioStore(tmp_path / "pg-files"))


@pytest.fixture(
    params=[
        pytest.param("file", id="file"),
        pytest.param(
            "postgres",
            id="postgres",
            marks=pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set -- opt-in Postgres backend"),
        ),
    ]
)
def store(request, tmp_path):
    """Either backend, behind the identical interface every caller uses."""
    if request.param == "file":
        yield _file_store(tmp_path)
        return
    pg = _postgres_store(tmp_path)
    try:
        yield pg
    finally:
        reset_postgres_tables(DSN)  # so re-runs against the same scratch DB are repeatable


def _holding(portfolio_id: str, security_id: str, as_of_date: str, value: float) -> Holding:
    return Holding(
        portfolio_id=portfolio_id, security_id=security_id, as_of_date=as_of_date,
        quantity=1.0, price=value, market_value=value, market_value_eur=value,
    )


def _seed_staggered_pulls(store) -> None:
    """Two portfolios on independent pull schedules -- the case the file
    store's docstring names as the reason as-of resolution exists at all.
    p1 is pulled monthly; p2 was pulled once, in January.
    """
    store.save_portfolio(Portfolio(portfolio_id="p1", name="Core Equity"))
    store.save_portfolio(Portfolio(portfolio_id="p2", name="Legacy Mandate"))
    store.save_company(CompanyRef(company_id="bmw", name="BMW AG", sector="Automobiles", country="DE"))
    store.save_security(
        SecurityRef(security_id="DE0005190003", isin="DE0005190003", name="BMW", asset_class="equity",
                    currency="EUR", company_id="bmw")
    )
    store.save_snapshot("p1", "2026-01-31", [_holding("p1", "DE0005190003", "2026-01-31", 100.0)])
    store.save_snapshot("p1", "2026-02-28", [_holding("p1", "DE0005190003", "2026-02-28", 110.0)])
    store.save_snapshot("p2", "2026-01-31", [_holding("p2", "DE0005190003", "2026-01-31", 500.0)])


# --- as-of resolution: the divergence this module exists for -------------


def test_load_holdings_as_of_uses_each_portfolios_latest_pull(store):
    """The requested date is p1's latest pull but not p2's. p2 must still
    contribute its January pull -- dropping it understates the total,
    silently, which is exactly what the Postgres backend used to do."""
    _seed_staggered_pulls(store)

    holdings = store.load_holdings_as_of("2026-02-28")

    assert sorted((h.portfolio_id, h.market_value_eur) for h in holdings) == [("p1", 110.0), ("p2", 500.0)]
    assert sum(h.market_value_eur for h in holdings) == 610.0


def test_load_holdings_as_of_between_snapshots_picks_the_prior_pull(store):
    """A date no portfolio was pulled on -- an analytic's explicit `as_of`,
    or an alert rule's -- resolves backwards, never to nothing."""
    _seed_staggered_pulls(store)

    holdings = store.load_holdings_as_of("2026-02-15")

    assert sorted((h.portfolio_id, h.market_value_eur) for h in holdings) == [("p1", 100.0), ("p2", 500.0)]


def test_load_holdings_as_of_before_any_snapshot_is_empty(store):
    _seed_staggered_pulls(store)

    assert store.load_holdings_as_of("2025-12-31") == []


def test_load_holdings_as_of_honours_the_portfolio_filter(store):
    _seed_staggered_pulls(store)

    only_p2 = store.load_holdings_as_of("2026-02-28", portfolio_ids=["p2"])

    assert [(h.portfolio_id, h.market_value_eur) for h in only_p2] == [("p2", 500.0)]


def test_load_snapshot_is_exact_date_not_as_of(store):
    """`load_snapshot` reads one pull; it must not silently fall back to an
    earlier one the way load_holdings_as_of does."""
    _seed_staggered_pulls(store)

    assert [h.market_value_eur for h in store.load_snapshot("p1", "2026-01-31")] == [100.0]
    assert store.load_snapshot("p1", "2026-02-15") == []
    assert store.load_snapshot("p2", "2026-02-28") == []


def test_snapshot_dates_and_latest(store):
    _seed_staggered_pulls(store)

    assert store.list_snapshot_dates("p1") == ["2026-01-31", "2026-02-28"]
    assert store.list_snapshot_dates("p2") == ["2026-01-31"]
    assert store.latest_snapshot_date("p1") == "2026-02-28"
    assert store.latest_snapshot_date("unknown") is None
    assert store.all_snapshot_dates() == ["2026-01-31", "2026-02-28"]


def test_resaving_a_snapshot_replaces_that_date_only(store):
    _seed_staggered_pulls(store)

    store.save_snapshot("p1", "2026-02-28", [_holding("p1", "DE0005190003", "2026-02-28", 999.0)])

    assert [h.market_value_eur for h in store.load_snapshot("p1", "2026-02-28")] == [999.0]
    assert [h.market_value_eur for h in store.load_snapshot("p1", "2026-01-31")] == [100.0]
    assert store.list_snapshot_dates("p1") == ["2026-01-31", "2026-02-28"]


# --- round-trips: a field dropped by one backend's mapping fails here ----


def test_portfolio_round_trip(store):
    portfolio = Portfolio(portfolio_id="p1", name="Core Equity", tags=["mandate:equity", "client:institutional"])
    store.save_portfolio(portfolio)

    assert store.get_portfolio("p1") == portfolio
    assert store.get_portfolio("nope") is None
    assert store.list_portfolios() == [portfolio]


def test_security_round_trip(store):
    security = SecurityRef(
        security_id="DE0005190003", isin="DE0005190003", name="BMW AG", asset_class="equity",
        currency="EUR", company_id="bmw",
    )
    store.save_company(CompanyRef(company_id="bmw", name="BMW AG"))
    store.save_security(security)

    assert store.get_security("DE0005190003") == security
    assert store.get_security("nope") is None
    assert store.list_securities() == [security]


def test_company_round_trip(store):
    company = CompanyRef(
        company_id="bmw", name="BMW AG", ticker="BMW", website="https://www.bmwgroup.com",
        cik="0000313616", country="DE", sector="Automobiles", isic_code="2910",
    )
    store.save_company(company)

    assert store.get_company("bmw") == company
    assert store.get_company("nope") is None
    assert store.list_companies() == [company]


def test_resolution_round_trip_and_review_filter(store):
    resolved = SecurityResolution(
        security_id="DE0005190003", company_id="bmw", confidence=0.99, method="isin_exact",
        needs_review=False, resolved_at="2026-01-31T00:00:00Z",
    )
    unresolved = SecurityResolution(
        security_id="XS9999999999", company_id=None, confidence=0.2, method="name_fuzzy",
        needs_review=True, resolved_at="2026-01-31T00:00:00Z",
    )
    store.save_resolution(resolved)
    store.save_resolution(unresolved)

    assert store.get_resolution("DE0005190003") == resolved
    assert store.get_resolution("nope") is None
    assert [r.security_id for r in store.list_resolutions_needing_review()] == ["XS9999999999"]


def test_holding_round_trip_keeps_every_field(store):
    """Both backends persist the full Holding, including the optional
    weight_pct and a non-default FX rate -- the hand-written ORM mapping
    drops a field silently otherwise."""
    store.save_portfolio(Portfolio(portfolio_id="p1", name="Core Equity"))
    store.save_security(SecurityRef(security_id="US0378331005", name="Apple", asset_class="equity", currency="USD"))
    holding = Holding(
        portfolio_id="p1", security_id="US0378331005", as_of_date="2026-01-31", quantity=12.5, price=190.0,
        market_value=2375.0, fx_rate_to_eur=0.92, market_value_eur=2185.0, weight_pct=3.75,
    )
    store.save_snapshot("p1", "2026-01-31", [holding])

    assert store.load_snapshot("p1", "2026-01-31") == [holding]


def test_upsert_semantics_are_not_duplicate_inserts(store):
    store.save_portfolio(Portfolio(portfolio_id="p1", name="Original"))
    store.save_portfolio(Portfolio(portfolio_id="p1", name="Renamed", tags=["updated"]))

    assert store.list_portfolios() == [Portfolio(portfolio_id="p1", name="Renamed", tags=["updated"])]


# --- the interface contract itself ---------------------------------------


def test_public_surfaces_match():
    """The `AttributeError` class of bug: a caller reaching a method only
    one backend has (it was `list_observation_keys`, via
    /api/portfolio/climate-conflicts). Compares classes, so this runs
    without a database."""
    from arp.storage.postgres_portfolio_store import PostgresPortfolioStore

    file_surface = {name for name in dir(PortfolioStore) if not name.startswith("_")}
    pg_surface = {name for name in dir(PostgresPortfolioStore) if not name.startswith("_")}

    assert file_surface - pg_surface == FILE_ONLY_METHODS
    # The Postgres store may add capabilities the file store can't offer
    # cheaply (the aggregation join), but must not shadow a file-only name.
    assert pg_surface & FILE_ONLY_METHODS == set()


@pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set -- opt-in Postgres backend")
def test_sql_aggregation_agrees_with_a_python_sum_over_the_same_as_of(tmp_path):
    """`aggregate_market_value_eur` is the reason this backend exists, so
    its as-of resolution must match load_holdings_as_of's exactly -- two
    ways of asking one question that used to disagree with the file store
    in the same way."""
    pg = _postgres_store(tmp_path)
    try:
        _seed_staggered_pulls(pg)

        by_portfolio = dict(pg.aggregate_market_value_eur("2026-02-28", "portfolio_id"))
        by_sector = dict(pg.aggregate_market_value_eur("2026-02-28", "sector"))
        holdings = pg.load_holdings_as_of("2026-02-28")

        assert by_portfolio == {"p1": 110.0, "p2": 500.0}
        assert by_sector == {"Automobiles": 610.0}
        assert sum(by_portfolio.values()) == sum(h.market_value_eur for h in holdings)

        # And a date between pulls resolves backwards here too.
        assert dict(pg.aggregate_market_value_eur("2026-02-15", "portfolio_id")) == {"p1": 100.0, "p2": 500.0}
    finally:
        reset_postgres_tables(DSN)
