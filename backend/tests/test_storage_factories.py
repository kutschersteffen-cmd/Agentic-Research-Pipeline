"""Unit tests for the backend-selection factories (no DB required) --
Postgres-specific behavior is covered separately in
test_postgres_portfolio_store.py, gated on a real instance."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from arp.config import Settings
from arp.retrieval.content_store_factory import build_hybrid_content_store
from arp.storage.document_search_factory import build_document_registry_reader
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


def test_portfolio_store_postgres_without_dsn_still_raises_defensively(tmp_path):
    """Settings validation now rejects this combination outright (see
    test_selecting_a_backend_without_its_connection_is_refused_at_construction),
    so the factory's own check is unreachable through the normal path. It
    stays as a guard for a Settings built around validation, and is
    asserted here through exactly that door."""
    settings = Settings.model_construct(
        **{**_settings(tmp_path).model_dump(), "portfolio_backend": "postgres", "postgres_dsn": None}
    )

    with pytest.raises(RuntimeError, match="postgres_dsn"):
        build_portfolio_store(settings)


def test_portfolio_store_postgres_with_dsn_selects_postgres_backend(tmp_path):
    store = build_portfolio_store(_settings(tmp_path, portfolio_backend="postgres", postgres_dsn="postgresql+psycopg://u:p@localhost/db"))
    assert type(store).__name__ == "PostgresPortfolioStore"


def test_hybrid_content_store_defaults_to_sqlite(tmp_path):
    store = build_hybrid_content_store(_settings(tmp_path))
    assert isinstance(store, DocumentContentStore)


def test_selecting_a_backend_without_its_connection_is_refused_at_construction(tmp_path):
    """The misconfiguration is now caught when Settings is built -- at
    startup, in the API and the CLI alike -- rather than being felt later
    as a silently different backend. Previously only
    build_portfolio_store raised, and only when it happened to be called;
    the embeddings factory quietly used SQLite instead."""
    for kwargs in (
        {"portfolio_backend": "postgres"},
        {"embeddings_backend": "postgres"},
        {"retrieval_backend": "opensearch"},
    ):
        with pytest.raises(ValidationError):
            _settings(tmp_path, **kwargs)


def test_hybrid_content_store_still_falls_back_rather_than_failing_a_run(tmp_path):
    """`build_hybrid_content_store` runs per field per company inside the
    retrieval graph, so it must not raise over configuration: hybrid
    retrieval is a cache, and failing a whole run for it would be worse
    than being slower. Reaching this fallback means validation was
    bypassed (model_construct here), which it also logs."""
    settings = Settings.model_construct(
        **{**_settings(tmp_path).model_dump(), "embeddings_backend": "postgres", "postgres_dsn": None}
    )

    store = build_hybrid_content_store(settings)

    assert isinstance(store, DocumentContentStore)


def test_hybrid_content_store_postgres_with_dsn_selects_pgvector(tmp_path):
    store = build_hybrid_content_store(
        _settings(tmp_path, embeddings_backend="postgres", postgres_dsn="postgresql+psycopg://u:p@localhost/db")
    )
    assert type(store).__name__ == "PgVectorEmbeddingsStore"


def test_document_registry_reader_defaults_to_sqlite(tmp_path):
    reader = build_document_registry_reader(_settings(tmp_path))
    assert isinstance(reader, DocumentContentStore)


def test_document_registry_reader_projection_without_dsn_falls_back_to_sqlite(tmp_path):
    reader = build_document_registry_reader(_settings(tmp_path, document_registry_projection_enabled=True))
    assert isinstance(reader, DocumentContentStore)


def test_document_registry_reader_with_dsn_selects_postgres(tmp_path):
    reader = build_document_registry_reader(
        _settings(tmp_path, document_registry_projection_enabled=True, postgres_dsn="postgresql+psycopg://u:p@localhost/db")
    )
    assert type(reader).__name__ == "PostgresDocumentRegistryReader"
