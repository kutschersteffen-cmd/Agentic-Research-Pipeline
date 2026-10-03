"""Unit tests for the blob stores. No real MinIO/S3 endpoint is needed: the S3 client is faked."""

from __future__ import annotations

import pytest

from arp.ingestion.indexing_config import IndexingConfig
from arp.storage import document_blob_store


def _config(**overrides) -> IndexingConfig:
    base = dict(
        object_store_endpoint_url="http://localhost:9000",
        object_store_access_key="arp",
        object_store_secret_key="arp12345",
        object_store_bucket="arp-documents",
        object_store_live_upload_enabled=True,
    )
    base.update(overrides)
    return IndexingConfig(**base)


def test_upload_document_puts_bytes_under_content_key(monkeypatch):
    """upload_document itself (the unconditional path arp db reindex
    object-store calls directly) -- mocks the S3 client since no real
    endpoint is available in unit tests."""
    put_calls = []

    class FakeClient:
        def put_object(self, Bucket, Key, Body):  # noqa: N803 - matches boto3's parameter casing
            put_calls.append((Bucket, Key, Body))

        def head_bucket(self, Bucket):  # noqa: N803
            pass

    monkeypatch.setattr("arp.storage.document_blob_store.get_client", lambda *a, **k: FakeClient())

    storage_uri = document_blob_store.upload_document(_config(), "abc123", b"raw bytes")

    assert storage_uri == "s3://arp-documents/abc123"
    assert put_calls == [("arp-documents", "abc123", b"raw bytes")]


def test_local_blob_store_roundtrip(tmp_path):
    store = document_blob_store.LocalBlobStore(tmp_path)
    assert not store.exists("abcdef")
    uri = store.put("abcdef", b"data")
    assert uri == "file://" + str((tmp_path / "ab" / "abcdef").resolve())
    assert store.exists("abcdef")
    assert store.get("abcdef") == b"data"


def test_blob_store_for_defaults_to_local(tmp_path):
    store = document_blob_store.blob_store_for(IndexingConfig(blob_store_dir=tmp_path))
    assert isinstance(store, document_blob_store.LocalBlobStore)
    with pytest.raises(document_blob_store.CaptureStoreError):
        document_blob_store.blob_store_for(IndexingConfig())


def test_blob_store_for_returns_object_store_when_enabled(monkeypatch):
    monkeypatch.setattr("arp.storage.document_blob_store.get_client", lambda *a, **k: object())
    monkeypatch.setattr("arp.storage.document_blob_store.ensure_bucket", lambda *a, **k: None)
    store = document_blob_store.blob_store_for(_config())
    assert isinstance(store, document_blob_store.DocumentBlobStore)
    assert store.uri("k") == "s3://arp-documents/k"
