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

from arp.storage.object_store_client import ensure_bucket, get_client


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
