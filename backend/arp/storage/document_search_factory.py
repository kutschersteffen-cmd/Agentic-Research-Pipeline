"""Single choke point for choosing a file/SQLite-backed document-registry
reader (default, DocumentContentStore) vs. a Postgres-backed one (opt-in,
requires postgres_dsn + Settings.document_registry_projection_enabled) --
mirrors portfolio_store_factory.py's exact shape. Read-only either way:
DocumentRegistry (SQLite) stays the only writable copy regardless of
which reader this returns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from arp.config import Settings
from arp.storage.document_store import DocumentContentStore

if TYPE_CHECKING:
    from arp.storage.postgres_document_projection import PostgresDocumentRegistryReader


def build_document_registry_reader(settings: Settings) -> DocumentContentStore | PostgresDocumentRegistryReader:
    file_reader = DocumentContentStore(settings.document_store_dir, enabled=settings.document_cache_enabled)
    if not settings.document_registry_projection_enabled or not settings.postgres_dsn:
        # Matches build_hybrid_content_store's own "optional secondary
        # backend, fall back rather than hard-fail" precedent -- this
        # projection is additive/read-only, not the sole source of truth
        # the way portfolio_backend is, so a misconfiguration (flag on,
        # no DSN) shouldn't break document lookups.
        return file_reader

    from arp.storage.postgres_document_projection import PostgresDocumentRegistryReader

    return PostgresDocumentRegistryReader(settings.postgres_dsn)
