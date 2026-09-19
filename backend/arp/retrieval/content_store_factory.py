"""Single choke point for choosing the hybrid-retrieval embeddings cache
backend (DocumentContentStore/SQLite, default, vs. PgVectorEmbeddingsStore/
Postgres, opt-in via Settings.embeddings_backend == "postgres") -- every
_gather_evidence node (field_graph.py, financials_graph.py, match_graph.py)
calls this rather than duplicating the branch.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from arp.config import Settings

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from arp.storage.document_store import DocumentContentStore
    from arp.storage.postgres_embeddings import PgVectorEmbeddingsStore


def build_hybrid_content_store(settings: Settings) -> DocumentContentStore | PgVectorEmbeddingsStore:
    """Constructed lazily, only on the path that actually uses it (hybrid
    retrieval enabled) -- a cheap connect + idempotent
    CREATE-IF-NOT-EXISTS either way, not a long-lived singleton, matching
    how this was already constructed inline before this factory existed.

    Still falls back to SQLite if the Postgres backend is selected without
    a DSN, deliberately: this runs per field per company inside the
    retrieval graph, so raising here would fail a run mid-flight over a
    configuration mistake, and hybrid retrieval is a cache -- the answer is
    the same either way, only slower. What changed is that the fallback is
    no longer the operator's only signal: Settings refuses to construct in
    that state at all (see config.Settings._selected_backends_have_their_
    connection), so the mistake is caught at startup, and reaching the
    fallback now means someone bypassed validation -- hence the warning.
    """
    if settings.embeddings_backend == "postgres":
        if settings.postgres_dsn:
            from arp.storage.postgres_embeddings import PgVectorEmbeddingsStore

            return PgVectorEmbeddingsStore(settings.postgres_dsn)
        logger.warning(
            "embeddings_backend is 'postgres' but postgres_dsn is not set; using the local SQLite embeddings "
            "cache for this call. Set ARP_POSTGRES_DSN, or set ARP_EMBEDDINGS_BACKEND=sqlite to make the choice "
            "explicit."
        )

    from arp.storage.document_store import DocumentContentStore

    return DocumentContentStore(settings.document_store_dir, enabled=settings.document_cache_enabled)
