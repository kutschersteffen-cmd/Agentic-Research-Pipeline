"""Bundles the small subset of Settings that the OpenSearch live-indexing
hook (arp/retrieval/search_indexer.py) and the object-store live-upload
hook (arp/storage/document_blob_store.py) need, so DocumentSource
implementations (LocalFileDocumentSource, EdgarDocumentSource) take one
narrow, explicit config object instead of the whole Settings -- matching
how those classes already take individual primitive values (user_agent,
cache_dir, ttl) rather than a Settings instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arp.config import Settings


@dataclass(frozen=True)
class IndexingConfig:
    opensearch_url: str | None = None
    search_live_indexing_enabled: bool = False
    object_store_endpoint_url: str | None = None
    object_store_access_key: str | None = None
    object_store_secret_key: str | None = None
    object_store_bucket: str = "arp-documents"
    object_store_live_upload_enabled: bool = False
    postgres_dsn: str | None = None
    document_registry_projection_enabled: bool = False

    @classmethod
    def from_settings(cls, settings: Settings) -> IndexingConfig:
        return cls(
            opensearch_url=settings.opensearch_url,
            search_live_indexing_enabled=settings.search_live_indexing_enabled,
            object_store_endpoint_url=settings.object_store_endpoint_url,
            object_store_access_key=settings.object_store_access_key,
            object_store_secret_key=settings.object_store_secret_key,
            object_store_bucket=settings.object_store_bucket,
            object_store_live_upload_enabled=settings.object_store_live_upload_enabled,
            postgres_dsn=settings.postgres_dsn,
            document_registry_projection_enabled=settings.document_registry_projection_enabled,
        )

    @property
    def opensearch_enabled(self) -> bool:
        return bool(self.opensearch_url and self.search_live_indexing_enabled)

    @property
    def object_store_enabled(self) -> bool:
        return bool(self.object_store_endpoint_url and self.object_store_live_upload_enabled)

    @property
    def document_registry_enabled(self) -> bool:
        return bool(self.postgres_dsn and self.document_registry_projection_enabled)
