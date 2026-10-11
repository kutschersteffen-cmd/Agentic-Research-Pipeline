"""Single choke point for building the document content store used by hybrid retrieval and ingestion
(every _gather_evidence node calls this rather than constructing one)."""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from arp.config import Settings
from arp.db.session import require_dsn

if TYPE_CHECKING:
    from arp.storage.document_store import DocumentContentStore


def content_store_for(settings: Settings) -> DocumentContentStore:
    from arp.storage.document_store import DocumentContentStore

    return DocumentContentStore(
        settings.document_store_dir, enabled=settings.document_cache_enabled, dsn=require_dsn(settings)
    )


def build_hybrid_content_store(settings: Settings) -> DocumentContentStore:
    """Cached for the process on the fields that choose it: this is called once per (company, field) inside
    the retrieval graph, and the store keeps no open connection, so one instance is safe to share."""
    return _build_hybrid_content_store(
        require_dsn(settings), settings.document_store_dir, settings.document_cache_enabled
    )


@cache
def _build_hybrid_content_store(dsn: str, document_store_dir: Path, document_cache_enabled: bool) -> DocumentContentStore:
    from arp.storage.document_store import DocumentContentStore

    return DocumentContentStore(document_store_dir, enabled=document_cache_enabled, dsn=dsn)
