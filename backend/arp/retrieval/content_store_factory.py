"""Single choke point for choosing the hybrid-retrieval embeddings cache
backend (DocumentContentStore/SQLite, default, vs. PgVectorEmbeddingsStore/
Postgres, opt-in via Settings.embeddings_backend == "postgres") -- every
_gather_evidence node (field_graph.py, financials_graph.py, match_graph.py)
calls this rather than duplicating the branch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from arp.config import Settings

if TYPE_CHECKING:
    from arp.storage.document_store import DocumentContentStore
    from arp.storage.postgres_embeddings import PgVectorEmbeddingsStore


def build_hybrid_content_store(settings: Settings) -> DocumentContentStore | PgVectorEmbeddingsStore:
    """Constructed lazily, only on the path that actually uses it (hybrid
    retrieval enabled) -- a cheap connect + idempotent
    CREATE-IF-NOT-EXISTS either way, not a long-lived singleton, matching
    how this was already constructed inline before this factory existed.
    """
    if settings.embeddings_backend == "postgres" and settings.postgres_dsn:
        from arp.storage.postgres_embeddings import PgVectorEmbeddingsStore

        return PgVectorEmbeddingsStore(settings.postgres_dsn)

    from arp.storage.document_store import DocumentContentStore

    return DocumentContentStore(settings.document_store_dir, enabled=settings.document_cache_enabled)
