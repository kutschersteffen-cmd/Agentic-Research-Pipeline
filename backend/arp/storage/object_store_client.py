"""Lazy S3-compatible object-store client (MinIO locally, any S3-compatible
endpoint in production), gated entirely on Settings.object_store_endpoint_url
-- mirrors arp/storage/postgres.py's exact pattern (lazy-import-on-first-use,
"not configured" vs "extra not installed" exception split) so a deployment
that never sets ARP_OBJECT_STORE_ENDPOINT_URL never needs boto3 installed.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from botocore.client import BaseClient


class ObjectStoreNotConfigured(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "Settings.object_store_endpoint_url is not set -- the immutable source-document object store is "
            "entirely opt-in. Set ARP_OBJECT_STORE_ENDPOINT_URL (e.g. http://localhost:9000 for local MinIO) to "
            "enable it. Documents stay in the local documents_dir either way, exactly as today."
        )


class ObjectStoreExtraNotInstalled(RuntimeError):
    def __init__(self, exc: Exception) -> None:
        super().__init__(
            "object_store_endpoint_url is set but boto3 isn't installed. Install the optional extra: "
            f"pip install -e '.[object_storage]'. Original import error: {exc}"
        )


@lru_cache
def get_client(endpoint_url: str, access_key: str | None, secret_key: str | None) -> BaseClient:
    """One cached boto3 S3 client per (endpoint, credentials) tuple for the
    process lifetime, matching postgres.get_engine's one-client-per-config
    pattern. Imports boto3 lazily so the rest of this codebase never pays
    an import cost, let alone a hard dependency, for a store nobody has
    opted into."""
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - exercised only without the optional extra
        raise ObjectStoreExtraNotInstalled(exc) from exc
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


def ensure_bucket(client: BaseClient, bucket: str) -> None:
    """Creates `bucket` if it doesn't already exist, idempotently -- mirrors
    postgres.ensure_schema's create-if-missing contract. Call once per fresh
    store (`arp db init-object-store`), not per request."""
    from botocore.exceptions import ClientError

    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)
