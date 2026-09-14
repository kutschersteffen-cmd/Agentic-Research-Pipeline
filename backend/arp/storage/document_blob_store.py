"""Immutable object-storage copy of each source document's original bytes,
keyed by the same content-addressed hash DocumentContentStore/derive_doc_id
already compute (arp/storage/document_registry.py) -- a document already
deduplicated in the SQLite parsed-content cache is deduplicated in object
storage too, for free. Selected via Settings.object_store_endpoint_url;
the local documents_dir remains the default and is entirely unaffected
when this isn't opted into.

Scope is deliberate: this store only ever holds the original, immutable
source file. It is never a replacement for DocumentContentStore's parsed-
text cache (that stays SQLite), never authoritative for anything queryable
(that's Postgres' job, see postgres_models.py) or searchable (that's
OpenSearch's job, see opensearch_indices.py). It exists purely so a
reviewer or auditor can retrieve the exact original PDF a citation came
from, even if the local working copy is gone.
"""

from __future__ import annotations

import logging

from arp.ingestion.indexing_config import IndexingConfig
from arp.storage.object_store_client import ensure_bucket, get_client

logger = logging.getLogger(__name__)


def upload_document_if_enabled(config: IndexingConfig, content_key: str, data: bytes) -> str | None:
    """Best-effort upload of a document's raw original bytes, called right
    after registration in DocumentRegistry (arp/ingestion/local_files.py,
    edgar.py). Gated on IndexingConfig.object_store_enabled; a no-op
    otherwise. Any upload failure is logged and swallowed -- never fails
    the ingestion call it's attached to -- and returns None so the caller
    knows not to record a storage_uri. A full backfill for documents
    registered before this was enabled is `arp db reindex object-store`.
    """
    if not config.object_store_enabled:
        return None
    try:
        return upload_document(config, content_key, data)
    except Exception:
        logger.warning("Object-store upload failed for content_key=%s", content_key, exc_info=True)
        return None


def upload_document(config: IndexingConfig, content_key: str, data: bytes) -> str:
    """Unconditional (no enabled-flag check, no exception handling) --
    `upload_document_if_enabled` is the guarded wrapper every live-ingestion
    hook uses; this is exposed separately for `arp db reindex object-store`,
    which wants a real exception on failure to count against its own
    uploaded/failed tally rather than a silently swallowed log line."""
    store = DocumentBlobStore(
        config.object_store_endpoint_url, config.object_store_access_key, config.object_store_secret_key, config.object_store_bucket
    )
    return store.put(content_key, data)


class DocumentBlobStore:
    def __init__(self, endpoint_url: str, access_key: str | None, secret_key: str | None, bucket: str) -> None:
        self._bucket = bucket
        self._client = get_client(endpoint_url, access_key, secret_key)
        ensure_bucket(self._client, bucket)

    def put(self, content_key: str, data: bytes) -> str:
        self._client.put_object(Bucket=self._bucket, Key=content_key, Body=data)
        return f"s3://{self._bucket}/{content_key}"

    def get(self, content_key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=content_key)
        return response["Body"].read()

    def exists(self, content_key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self._bucket, Key=content_key)
            return True
        except ClientError:
            return False
