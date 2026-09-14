"""Read-model projection of DocumentRegistry (SQLite, always
authoritative -- see arp/storage/document_registry.py) into
DocumentRegistryModel (arp/storage/postgres_models.py). SQLite stays the
only writable copy; this module only ever reads it and writes derived
rows, plus offers a read-only Postgres-backed reader for callers that
want the relational-join lookups this projection exists for (joining
OpenSearch's doc_id-only hits back to company/doc_type facts, or
cross-company dedup queries).
"""

from __future__ import annotations

import logging

from arp.ingestion.indexing_config import IndexingConfig
from arp.storage.document_registry import StoredDocumentRef
from arp.storage.postgres import get_engine

logger = logging.getLogger(__name__)


def sync_document(dsn: str, doc_ref: StoredDocumentRef) -> None:
    """Idempotent upsert of one document's registry row."""
    from sqlalchemy.orm import Session

    from arp.schemas.common import now_iso
    from arp.storage.postgres_models import DocumentRegistryModel

    engine = get_engine(dsn)
    with Session(engine) as session:
        existing = session.get(DocumentRegistryModel, doc_ref.doc_id)
        now = now_iso()
        if existing is None:
            session.add(
                DocumentRegistryModel(
                    doc_id=doc_ref.doc_id,
                    company_id=doc_ref.company_id,
                    doc_type=doc_ref.doc_type,
                    content_key=doc_ref.content_key,
                    title=doc_ref.title,
                    local_path=doc_ref.local_path,
                    source_url=doc_ref.source_url,
                    storage_uri=doc_ref.storage_uri,
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
        else:
            existing.title = doc_ref.title
            existing.local_path = doc_ref.local_path
            existing.source_url = doc_ref.source_url
            # Never clobber a previously-synced storage_uri with None --
            # a cache-hit re-sync (edgar.py's _get_filing_text on an
            # already-parsed filing) has no new archival info to report,
            # it isn't reporting the document was un-archived.
            if doc_ref.storage_uri is not None:
                existing.storage_uri = doc_ref.storage_uri
            existing.last_seen_at = now
        session.commit()


def sync_all(dsn: str, content_store) -> int:
    """Backfills every registered document -- used by `arp db reindex
    documents`. `content_store` is a DocumentContentStore."""
    refs = content_store.list_all_documents()
    for ref in refs:
        sync_document(dsn, ref)
    return len(refs)


def sync_document_if_enabled(config: IndexingConfig, doc_ref: StoredDocumentRef) -> None:
    """Best-effort: called right after a document is registered
    (arp/ingestion/local_files.py, edgar.py). Any failure is logged and
    swallowed -- never fails the ingestion call it's attached to."""
    if not config.document_registry_enabled:
        return
    try:
        sync_document(config.postgres_dsn, doc_ref)
    except Exception:
        logger.warning("Postgres document-registry sync failed for doc_id=%s", doc_ref.doc_id, exc_info=True)


class PostgresDocumentRegistryReader:
    """Read-only Postgres-backed alternative to querying DocumentRegistry
    directly -- same StoredDocumentRef shape, for callers that want a
    relational join against the projection (e.g. a future search-API
    enrichment step) instead of scanning SQLite row-by-row."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._engine = get_engine(dsn)

    def resolve_document(self, doc_id: str) -> StoredDocumentRef | None:
        from sqlalchemy.orm import Session

        from arp.storage.postgres_models import DocumentRegistryModel

        with Session(self._engine) as session:
            row = session.get(DocumentRegistryModel, doc_id)
            if row is None:
                return None
            return _ref_from_row(row)

    def list_by_content_keys(self, content_keys: list[str]) -> dict[str, StoredDocumentRef]:
        if not content_keys:
            return {}
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from arp.storage.postgres_models import DocumentRegistryModel

        with Session(self._engine) as session:
            rows = session.scalars(
                select(DocumentRegistryModel).where(DocumentRegistryModel.content_key.in_(content_keys))
            ).all()
            return {row.content_key: _ref_from_row(row) for row in rows}


def _ref_from_row(row) -> StoredDocumentRef:
    return StoredDocumentRef(
        doc_id=row.doc_id,
        company_id=row.company_id,
        doc_type=row.doc_type,
        content_key=row.content_key,
        title=row.title,
        local_path=row.local_path,
        source_url=row.source_url,
        storage_uri=row.storage_uri,
    )
