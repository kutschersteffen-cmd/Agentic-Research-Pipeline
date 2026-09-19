"""`analytics.execute` must produce the same AggregationResult whether the
`market_value_sum` metric was summed in Python over loaded snapshots or by
one grouped SQL query.

The SQL path (PostgresPortfolioStore.aggregate_holdings_by) is what makes
the relational backend worth configuring, and it was dead code until it
was wired into `execute` -- so these tests are the thing that keeps wiring
it up from quietly changing any number. Every assertion compares the two
results field by field, including the counts, the "(unresolved)" bucket
and the row ordering.

Skipped without ARP_TEST_POSTGRES_DSN, like every other test that needs a
real instance.
"""

from __future__ import annotations

import os

import pytest

from arp.portfolio import analytics
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import AnalyticSpec, Holding, Portfolio, SecurityRef
from arp.storage.portfolio_store import PortfolioStore
from tests.postgres_helpers import reset_postgres_tables

DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set -- opt-in Postgres backend")

_COMPANIES = [
    CompanyRef(company_id="bmw", name="BMW AG", sector="Automobiles", country="DE"),
    CompanyRef(company_id="sap", name="SAP SE", sector="Software", country="DE"),
    CompanyRef(company_id="aapl", name="Apple Inc", sector="Technology Hardware", country="US"),
]
_SECURITIES = [
    SecurityRef(security_id="DE0005190003", isin="DE0005190003", name="BMW", asset_class="equity", currency="EUR", company_id="bmw"),
    SecurityRef(security_id="DE0007164600", isin="DE0007164600", name="SAP", asset_class="equity", currency="EUR", company_id="sap"),
    SecurityRef(security_id="US0378331005", isin="US0378331005", name="Apple", asset_class="equity", currency="USD", company_id="aapl"),
    # Deliberately unresolved: no company_id, so sector/country/company_id
    # group it under "(unresolved)" in both paths.
    SecurityRef(security_id="XS1234567890", isin="XS1234567890", name="Unidentified Note", asset_class="corporate_bond", currency="EUR"),
]
_HOLDINGS = [
    # p1 is pulled twice; p2 only in January -- so the default "latest
    # date" query has to resolve p2 backwards (see F1).
    ("p1", "DE0005190003", "2026-01-31", 1_000.0),
    ("p1", "DE0007164600", "2026-01-31", 2_500.0),
    ("p1", "DE0005190003", "2026-02-28", 1_100.0),
    ("p1", "US0378331005", "2026-02-28", 4_000.0),
    ("p1", "XS1234567890", "2026-02-28", 750.0),
    ("p2", "DE0007164600", "2026-01-31", 3_300.0),
    ("p2", "XS1234567890", "2026-01-31", 120.0),
]


def _seed(store) -> None:
    store.save_portfolio(Portfolio(portfolio_id="p1", name="Core Equity"))
    store.save_portfolio(Portfolio(portfolio_id="p2", name="Legacy Mandate"))
    for company in _COMPANIES:
        store.save_company(company)
    for security in _SECURITIES:
        store.save_security(security)
    by_snapshot: dict[tuple[str, str], list[Holding]] = {}
    for portfolio_id, security_id, as_of_date, value in _HOLDINGS:
        by_snapshot.setdefault((portfolio_id, as_of_date), []).append(
            Holding(
                portfolio_id=portfolio_id, security_id=security_id, as_of_date=as_of_date,
                quantity=1.0, price=value, market_value=value, market_value_eur=value,
            )
        )
    for (portfolio_id, as_of_date), holdings in by_snapshot.items():
        store.save_snapshot(portfolio_id, as_of_date, holdings)


@pytest.fixture
def stores(tmp_path):
    """The same dataset in both backends, plus the securities/companies
    lookups `execute` takes."""
    from arp.storage.postgres import ensure_schema
    from arp.storage.postgres_portfolio_store import PostgresPortfolioStore

    ensure_schema(DSN)
    # Emptied before seeding, not only after: the by-sector/by-country
    # assertions below are unfiltered, so any row left in this scratch
    # database by another suite would change their totals.
    reset_postgres_tables(DSN)
    file_store = PortfolioStore(tmp_path / "files")
    pg_store = PostgresPortfolioStore(DSN, PortfolioStore(tmp_path / "pg-files"))
    _seed(file_store)
    _seed(pg_store)
    securities = {s.security_id: s for s in _SECURITIES}
    companies = {c.company_id: c for c in _COMPANIES}
    try:
        yield file_store, pg_store, securities, companies
    finally:
        reset_postgres_tables(DSN)


def _spec(**kwargs) -> AnalyticSpec:
    defaults = {"name": "parity", "group_by": "sector", "metric": "market_value_sum"}
    return AnalyticSpec(**{**defaults, **kwargs})


@pytest.mark.parametrize(
    "spec_kwargs",
    [
        pytest.param({"group_by": "sector"}, id="by-sector"),
        pytest.param({"group_by": "country"}, id="by-country"),
        pytest.param({"group_by": "company_id"}, id="by-issuer"),
        pytest.param({"group_by": "company_name"}, id="by-issuer-name"),
        pytest.param({"group_by": "portfolio_id"}, id="by-portfolio"),
        pytest.param({"group_by": "asset_class"}, id="by-asset-class"),
        pytest.param({"group_by": "currency"}, id="by-currency"),
        pytest.param({"group_by": "sector", "as_of": "2026-01-31"}, id="explicit-as-of"),
        pytest.param({"group_by": "sector", "as_of": "2026-02-15"}, id="as-of-between-snapshots"),
        pytest.param({"group_by": "sector", "portfolio_filter": ["p1"]}, id="portfolio-filtered"),
        pytest.param({"group_by": "sector", "security_filter": {"asset_class": "equity"}}, id="security-filtered"),
        pytest.param({"group_by": "company_name", "security_filter": {"currency": "EUR"}}, id="currency-filtered"),
    ],
)
def test_sql_and_python_paths_agree(stores, spec_kwargs):
    file_store, pg_store, securities, companies = stores
    spec = _spec(**spec_kwargs)

    from_files = analytics.execute(spec, file_store, securities, companies)
    from_sql = analytics.execute(spec, pg_store, securities, companies)

    assert from_sql.as_of == from_files.as_of
    assert from_sql.group_by == from_files.group_by
    assert from_sql.metric == from_files.metric
    assert from_sql.total_market_value_eur == from_files.total_market_value_eur
    assert [(r.group_value, r.market_value_eur, r.holding_count) for r in from_sql.rows] == [
        (r.group_value, r.market_value_eur, r.holding_count) for r in from_files.rows
    ]


def test_the_sql_path_really_was_taken(stores):
    """Guards the guard: if `_try_aggregate_in_sql` silently returned None
    for the Postgres store, every assertion above would be comparing the
    Python path with itself and would pass no matter what the SQL did."""
    file_store, pg_store, _securities, _companies = stores

    assert analytics._try_aggregate_in_sql(_spec(group_by="sector"), pg_store) is not None
    # ...and the file store must NOT be routed into SQL it cannot run.
    assert analytics._try_aggregate_in_sql(_spec(group_by="sector"), file_store) is None


def test_unresolved_issuers_land_in_the_same_bucket(stores):
    """The corporate bond has no resolved issuer. Both paths must report it
    under "(unresolved)" rather than dropping it from the total."""
    file_store, pg_store, securities, companies = stores
    spec = _spec(group_by="sector")

    from_files = analytics.execute(spec, file_store, securities, companies)
    from_sql = analytics.execute(spec, pg_store, securities, companies)

    unresolved_files = next(r for r in from_files.rows if r.group_value == "(unresolved)")
    unresolved_sql = next(r for r in from_sql.rows if r.group_value == "(unresolved)")
    assert unresolved_sql.market_value_eur == unresolved_files.market_value_eur
    assert unresolved_sql.holding_count == unresolved_files.holding_count


def test_non_market_value_metrics_still_go_through_python(stores):
    """`count` and `weighted_avg_datapoint` are deliberately not pushed
    into SQL -- the latter needs the file-based observation cascade. They
    must keep working unchanged against the Postgres store."""
    _file_store, pg_store, securities, companies = stores

    counted = analytics.execute(_spec(group_by="sector", metric="count"), pg_store, securities, companies)

    assert sum(r.holding_count for r in counted.rows) == 5  # p1's Feb pull (3) + p2's Jan pull (2)
    assert counted.metric == "count"
