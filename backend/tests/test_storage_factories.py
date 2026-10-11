"""Unit tests for the backend-selection factories (no DB required) --
Postgres-specific behavior is covered separately in
test_postgres_portfolio_store.py, gated on a real instance."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from arp.config import Settings
from arp.retrieval.content_store_factory import build_hybrid_content_store
from arp.storage.document_store import DocumentContentStore
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


def test_portfolio_store_without_dsn_raises(tmp_path):
    settings = Settings.model_construct(**{**_settings(tmp_path).model_dump(), "postgres_dsn": None})
    with pytest.raises(RuntimeError, match="ARP_POSTGRES_DSN"):
        build_portfolio_store(settings)


def test_portfolio_store_is_the_postgres_store(tmp_path):
    store = build_portfolio_store(_settings(tmp_path, postgres_dsn="postgresql+psycopg://u:p@localhost/db"))
    assert type(store).__name__ == "PostgresPortfolioStore"


def test_hybrid_content_store_is_the_document_content_store(tmp_path, pg):
    store = build_hybrid_content_store(_settings(tmp_path, postgres_dsn=pg))
    assert isinstance(store, DocumentContentStore)


def test_selecting_a_backend_without_its_connection_is_refused_at_construction(tmp_path):
    """Caught when Settings is built (startup, API and CLI alike), not felt later as a different backend."""
    with pytest.raises(ValidationError):
        _settings(tmp_path, retrieval_backend="opensearch")
