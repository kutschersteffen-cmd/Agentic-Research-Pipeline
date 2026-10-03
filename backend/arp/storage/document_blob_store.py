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

import hashlib
import logging
from pathlib import Path

from arp.ingestion.indexing_config import IndexingConfig
from arp.storage.atomic_io import atomic_write_bytes
from arp.storage.object_store_client import ensure_bucket, get_client

logger = logging.getLogger(__name__)


class CaptureStoreError(RuntimeError):
    """The original bytes could not be stored and verified."""


class LocalBlobStore:
    """Default store: `root/<key[:2]>/<key>` on local disk."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def _path(self, content_key: str) -> Path:
        return self._root / content_key[:2] / content_key

    def uri(self, content_key: str) -> str:
        return "file://" + str(self._path(content_key).resolve())

    def put(self, content_key: str, data: bytes) -> str:
        atomic_write_bytes(self._path(content_key), data)
        return self.uri(content_key)

    def get(self, content_key: str) -> bytes:
        return self._path(content_key).read_bytes()

    def exists(self, content_key: str) -> bool:
        return self._path(content_key).is_file()


def upload_document(config: IndexingConfig, content_key: str, data: bytes) -> str:
    """Unconditional S3 upload that raises on failure, for
    `arp db reindex object-store` to count against its own uploaded/failed
    tally. Live ingestion goes through `upload_or_fail` instead."""
    store = DocumentBlobStore(
        config.object_store_endpoint_url, config.object_store_access_key, config.object_store_secret_key, config.object_store_bucket
    )
    return store.put(content_key, data)


class DocumentBlobStore:
    def __init__(self, endpoint_url: str, access_key: str | None, secret_key: str | None, bucket: str) -> None:
        self._bucket = bucket
        self._client = get_client(endpoint_url, access_key, secret_key)
        ensure_bucket(self._client, bucket)

    def uri(self, content_key: str) -> str:
        return f"s3://{self._bucket}/{content_key}"

    def put(self, content_key: str, data: bytes) -> str:
        self._client.put_object(Bucket=self._bucket, Key=content_key, Body=data)
        return self.uri(content_key)

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


def blob_store_for(config: IndexingConfig) -> LocalBlobStore | DocumentBlobStore:
    if config.object_store_enabled:
        return DocumentBlobStore(
            config.object_store_endpoint_url, config.object_store_access_key, config.object_store_secret_key, config.object_store_bucket
        )
    if config.blob_store_dir is None:
        raise CaptureStoreError("no blob store configured: set blob_store_dir or the object store")
    return LocalBlobStore(config.blob_store_dir)


def upload_or_fail(store: LocalBlobStore | DocumentBlobStore, content_key: str, data: bytes) -> str:
    """Stores `data` under `content_key` (its sha256) and reads it back to
    verify. Skips the put when the blob is already there. Any error or hash
    mismatch raises CaptureStoreError, so a document never counts as
    collected without a verified copy."""
    try:
        if hashlib.sha256(data).hexdigest() != content_key:
            raise ValueError("content_key is not the sha256 of the bytes")
        uri = store.uri(content_key)
        if not store.exists(content_key):
            uri = store.put(content_key, data)
        if hashlib.sha256(store.get(content_key)).hexdigest() != content_key:
            raise ValueError("hash mismatch on re-read")
        return uri
    except Exception as exc:
        raise CaptureStoreError(f"store failed for {content_key}: {exc}") from exc
