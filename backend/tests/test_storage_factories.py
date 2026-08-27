"""Unit tests for the backend-selection factories (no DB required) --
Postgres-specific behavior is covered separately in
test_postgres_portfolio_store.py, gated on a real instance."""

from __future__ import annotations

from arp.config import Settings
from arp.retrieval.content_store_factory import build_hybrid_content_store
from arp.storage.document_store import DocumentContentStore
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.portfolio_store_factory import build_portfolio_store


def _settings(tmp_path, **overrides) -> Settings:
    return Settings(
        anthropic_api_key="unused",
        runs_dir=tmp_path / "runs",
        documents_dir=tmp_path / "docs",
        cache_dir=tmp_path / "cache",
        discovery_state_dir=tmp_path / "disc",
        portfolios_dir=tmp_path / "portfolios",
        document_store_dir=tmp_path / "docstore",
        **overrides,
    )


def test_portfolio_store_defaults_to_file_backend(tmp_path):
    store = build_portfolio_store(_settings(tmp_path))
    assert isinstance(store, PortfolioStore)


def test_portfolio_store_postgres_without_dsn_raises(tmp_path):
    import pytest

    with pytest.raises(RuntimeError, match="postgres_dsn"):
        build_portfolio_store(_settings(tmp_path, portfolio_backend="postgres"))


def test_portfolio_store_postgres_with_dsn_selects_postgres_backend(tmp_path):
    store = build_portfolio_store(_settings(tmp_path, portfolio_backend="postgres", postgres_dsn="postgresql+psycopg://u:p@localhost/db"))
    assert type(store).__name__ == "PostgresPortfolioStore"


def test_hybrid_content_store_defaults_to_sqlite(tmp_path):
    store = build_hybrid_content_store(_settings(tmp_path))
    assert isinstance(store, DocumentContentStore)


def test_hybrid_content_store_postgres_requires_dsn_falls_back_to_sqlite(tmp_path):
    # embeddings_backend=postgres but no DSN configured -- falls back to
    # the always-available default rather than raising, since hybrid
    # retrieval itself is optional and shouldn't hard-fail a run over a
    # misconfigured secondary backend choice.
    store = build_hybrid_content_store(_settings(tmp_path, embeddings_backend="postgres"))
    assert isinstance(store, DocumentContentStore)


def test_hybrid_content_store_postgres_with_dsn_selects_pgvector(tmp_path):
    store = build_hybrid_content_store(
        _settings(tmp_path, embeddings_backend="postgres", postgres_dsn="postgresql+psycopg://u:p@localhost/db")
    )
    assert type(store).__name__ == "PgVectorEmbeddingsStore"
