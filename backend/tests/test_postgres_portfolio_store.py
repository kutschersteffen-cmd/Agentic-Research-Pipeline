"""Integration tests against a real Postgres+pgvector instance -- skipped
entirely unless ARP_TEST_POSTGRES_DSN is set, so this suite stays
network/database-free by default (see conftest.py's philosophy). Point it
at a scratch database, e.g.:

    createdb arp_test && psql arp_test -c "CREATE EXTENSION vector;"
    ARP_TEST_POSTGRES_DSN=postgresql+psycopg://postgres:postgres@localhost:5432/arp_test pytest tests/test_postgres_portfolio_store.py

Every test cleans up its own rows so the suite is repeatable against the
same scratch database.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, Portfolio, SecurityRef, SecurityResolution
from arp.storage.portfolio_store import PortfolioStore

DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set -- opt-in Postgres integration test")


@pytest.fixture
def store(tmp_path):
    from arp.storage.postgres import ensure_schema
    from arp.storage.postgres_portfolio_store import PostgresPortfolioStore

    ensure_schema(DSN)
    pg = PostgresPortfolioStore(DSN, PortfolioStore(tmp_path / "files"))
    yield pg
    # Clean up so re-runs against the same scratch DB are repeatable.
    from sqlalchemy import delete

    from arp.storage.postgres_models import CompanyModel, HoldingModel, PortfolioModel, SecurityModel, SecurityResolutionModel

    with pg._session() as session:
        for model in (HoldingModel, SecurityResolutionModel, SecurityModel, CompanyModel, PortfolioModel):
            session.execute(delete(model))
        session.commit()


def test_portfolio_roundtrip(store):
    store.save_portfolio(Portfolio(portfolio_id="p1", name="Test Fund", tags=["mandate:equity"]))
    assert store.get_portfolio("p1") == Portfolio(portfolio_id="p1", name="Test Fund", tags=["mandate:equity"])
    assert store.get_portfolio("nonexistent") is None
    assert [p.portfolio_id for p in store.list_portfolios()] == ["p1"]


def test_save_portfolio_upserts_not_duplicates(store):
    store.save_portfolio(Portfolio(portfolio_id="p1", name="Original", tags=[]))
    store.save_portfolio(Portfolio(portfolio_id="p1", name="Renamed", tags=["updated"]))
    portfolios = store.list_portfolios()
    assert len(portfolios) == 1
    assert portfolios[0].name == "Renamed"
    assert portfolios[0].tags == ["updated"]


def test_company_and_security_roundtrip(store):
    store.save_company(CompanyRef(company_id="bmw", name="BMW AG", sector="Automobiles", country="DE"))
    store.save_security(SecurityRef(security_id="DE0005190003", isin="DE0005190003", name="BMW", asset_class="equity", currency="EUR", company_id="bmw"))

    company = store.get_company("bmw")
    assert company is not None
    assert company.sector == "Automobiles"

    security = store.get_security("DE0005190003")
    assert security is not None
    assert security.company_id == "bmw"
    assert [c.company_id for c in store.list_companies()] == ["bmw"]
    assert [s.security_id for s in store.list_securities()] == ["DE0005190003"]


def test_resolution_needs_review_filter(store):
    store.save_company(CompanyRef(company_id="bmw", name="BMW AG"))
    store.save_resolution(SecurityResolution(security_id="s1", company_id="bmw", confidence=0.95, method="isin_exact", needs_review=False))
    store.save_resolution(SecurityResolution(security_id="s2", company_id=None, confidence=0.2, method="name_fuzzy", needs_review=True))

    flagged = store.list_resolutions_needing_review()
    assert [r.security_id for r in flagged] == ["s2"]
    assert store.get_resolution("s1").confidence == 0.95


def test_snapshot_save_load_and_resave_is_idempotent(store):
    store.save_portfolio(Portfolio(portfolio_id="p1", name="Fund"))
    store.save_security(SecurityRef(security_id="s1", name="Sec 1", asset_class="equity", currency="EUR"))

    holding = Holding(
        portfolio_id="p1", security_id="s1", as_of_date="2026-01-01", quantity=100, price=50.0,
        market_value=5000.0, fx_rate_to_eur=1.0, market_value_eur=5000.0,
    )
    store.save_snapshot("p1", "2026-01-01", [holding])
    loaded = store.load_snapshot("p1", "2026-01-01")
    assert len(loaded) == 1
    assert loaded[0].market_value_eur == 5000.0

    # Re-saving the same date must replace, not duplicate.
    updated = holding.model_copy(update={"market_value_eur": 6000.0})
    store.save_snapshot("p1", "2026-01-01", [updated])
    loaded_again = store.load_snapshot("p1", "2026-01-01")
    assert len(loaded_again) == 1
    assert loaded_again[0].market_value_eur == 6000.0

    assert store.list_snapshot_dates("p1") == ["2026-01-01"]
    assert store.latest_snapshot_date("p1") == "2026-01-01"
    assert store.all_snapshot_dates() == ["2026-01-01"]


def test_load_holdings_as_of_filters_by_portfolio(store):
    store.save_portfolio(Portfolio(portfolio_id="p1", name="Fund 1"))
    store.save_portfolio(Portfolio(portfolio_id="p2", name="Fund 2"))
    store.save_security(SecurityRef(security_id="s1", name="Sec 1", asset_class="equity", currency="EUR"))

    for pid in ("p1", "p2"):
        store.save_snapshot(
            pid, "2026-01-01",
            [Holding(portfolio_id=pid, security_id="s1", as_of_date="2026-01-01", quantity=1, price=100, market_value=100, market_value_eur=100)],
        )

    only_p1 = store.load_holdings_as_of("2026-01-01", portfolio_ids=["p1"])
    assert [h.portfolio_id for h in only_p1] == ["p1"]

    both = store.load_holdings_as_of("2026-01-01")
    assert sorted(h.portfolio_id for h in both) == ["p1", "p2"]


def test_aggregate_market_value_eur_by_sector_uses_the_company_join(store):
    """The concrete payoff of the relational store over the file-based
    one: one SQL query joins holdings -> securities -> companies and
    sums by sector, instead of loading every JSONL row into Python."""
    store.save_company(CompanyRef(company_id="bmw", name="BMW AG", sector="Automobiles"))
    store.save_company(CompanyRef(company_id="sap", name="SAP SE", sector="Software"))
    store.save_security(SecurityRef(security_id="s-bmw", name="BMW", asset_class="equity", currency="EUR", company_id="bmw"))
    store.save_security(SecurityRef(security_id="s-sap", name="SAP", asset_class="equity", currency="EUR", company_id="sap"))
    store.save_portfolio(Portfolio(portfolio_id="p1", name="Fund"))
    store.save_snapshot(
        "p1", "2026-01-01",
        [
            Holding(portfolio_id="p1", security_id="s-bmw", as_of_date="2026-01-01", quantity=1, price=1000, market_value=1000, market_value_eur=1000),
            Holding(portfolio_id="p1", security_id="s-sap", as_of_date="2026-01-01", quantity=1, price=2000, market_value=2000, market_value_eur=2000),
        ],
    )

    rows = store.aggregate_market_value_eur("2026-01-01", group_by="sector")
    by_sector = dict(rows)
    assert by_sector["Automobiles"] == 1000.0
    assert by_sector["Software"] == 2000.0


def test_observations_and_news_delegate_to_file_store(store):
    """Non-relational surfaces (observations/news/flags/analytics) are
    delegated to a wrapped PortfolioStore, not reimplemented -- proven by
    round-tripping through the Postgres-backed facade."""
    from arp.schemas.portfolio import DataPointObservation

    obs = DataPointObservation(
        company_id="bmw", field_id="waci", field_name="WACI", value=42.0, source="internal_api", period="2026-01-01"
    )
    store.append_observation(obs)
    loaded = store.load_observations("bmw", "waci")
    assert len(loaded) == 1
    assert loaded[0].value == 42.0


def test_pgvector_embeddings_store_roundtrip():
    from arp.storage.postgres import ensure_schema
    from arp.storage.postgres_embeddings import PgVectorEmbeddingsStore

    ensure_schema(DSN)
    pg_embeddings = PgVectorEmbeddingsStore(DSN)

    vectors = {"chunk-a": np.array([0.1, 0.2, 0.3], dtype=np.float32)}
    # Pad to EMBED_DIM so the fixed-width pgvector column accepts it.
    from arp.retrieval.embeddings import EMBED_DIM

    padded = {k: np.pad(v, (0, EMBED_DIM - len(v))) for k, v in vectors.items()}
    pg_embeddings.store_embeddings(padded, "test-model")

    looked_up = pg_embeddings.lookup_embeddings(["chunk-a", "chunk-missing"], "test-model")
    assert set(looked_up.keys()) == {"chunk-a"}
    np.testing.assert_allclose(looked_up["chunk-a"], padded["chunk-a"], atol=1e-5)

    # Cleanup.
    from sqlalchemy import delete

    from arp.storage.postgres_models import ChunkEmbeddingModel

    with pg_embeddings._Session(pg_embeddings._engine) as session:
        session.execute(delete(ChunkEmbeddingModel).where(ChunkEmbeddingModel.chunk_id == "chunk-a"))
        session.commit()
