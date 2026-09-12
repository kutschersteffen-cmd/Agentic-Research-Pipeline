"""Best-effort OpenSearch live-indexing hook, called right after a document
is registered in DocumentRegistry (arp/ingestion/local_files.py, edgar.py).
Gated on IndexingConfig.opensearch_enabled (both opensearch_url and
search_live_indexing_enabled must be set); a no-op otherwise, so opting
into OpenSearch never changes ingestion behavior for anyone who hasn't
enabled live indexing. Any indexing failure is logged and swallowed --
same "derived state, safe to lose" contract as DocumentContentStore's own
SQLite cache -- never fails the ingestion call it's attached to.

A full backfill for documents registered before this was enabled (or for
a failed live-indexing attempt) is `arp db reindex opensearch`.
"""

from __future__ import annotations

import logging

from arp.ingestion.indexing_config import IndexingConfig
from arp.ingestion.parsing import chunk_document
from arp.schemas.common import DocType, SourceDocument

logger = logging.getLogger(__name__)


def index_document_if_enabled(
    config: IndexingConfig, *, doc_id: str, company_id: str, doc_type: DocType, title: str, full_text: str
) -> None:
    if not config.opensearch_enabled:
        return
    try:
        index_document(config, doc_id=doc_id, company_id=company_id, doc_type=doc_type, title=title, full_text=full_text)
    except Exception:
        logger.warning("OpenSearch live indexing failed for doc_id=%s", doc_id, exc_info=True)


def index_document(
    config: IndexingConfig, *, doc_id: str, company_id: str, doc_type: DocType, title: str, full_text: str
) -> None:
    """Unconditional (no enabled-flag check, no exception handling) --
    `index_document_if_enabled` is the guarded wrapper every live-ingestion
    hook uses; this is exposed separately for `arp db reindex opensearch`,
    which wants a real exception on failure to count against its own
    indexed/failed tally rather than a silently swallowed log line."""
    from opensearchpy.helpers import bulk

    from arp.storage.opensearch_client import get_client

    client = get_client(config.opensearch_url)
    doc = SourceDocument(doc_id=doc_id, company_id=company_id, doc_type=doc_type, title=title, full_text=full_text)
    chunks = chunk_document(doc)

    actions = [
        {
            "_index": "arp-documents",
            "_id": doc_id,
            "_source": {"doc_id": doc_id, "company_id": company_id, "doc_type": doc_type.value, "title": title},
        }
    ]
    actions.extend(
        {
            "_index": "arp-chunks",
            "_id": chunk.chunk_id,
            "_source": {
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "company_id": chunk.company_id,
                "doc_type": chunk.doc_type.value,
                "text": chunk.text,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
            },
        }
        for chunk in chunks
    )
    bulk(client, actions)
