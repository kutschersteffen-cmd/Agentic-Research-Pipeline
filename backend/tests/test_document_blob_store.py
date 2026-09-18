"""Unit tests for the object-store live-upload hook -- no real MinIO/S3
endpoint required: upload_document (the real work) is monkeypatched out,
so these tests only verify upload_document_if_enabled's own contract
(gating, exception-swallowing), not S3's behavior."""

from __future__ import annotations

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


def test_noop_when_endpoint_unset(monkeypatch):
    calls = []
    monkeypatch.setattr(document_blob_store, "upload_document", lambda *a, **k: calls.append((a, k)))

    result = document_blob_store.upload_document_if_enabled(_config(object_store_endpoint_url=None), "key", b"data")

    assert result is None
    assert calls == []


def test_noop_when_live_upload_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(document_blob_store, "upload_document", lambda *a, **k: calls.append((a, k)))

    result = document_blob_store.upload_document_if_enabled(_config(object_store_live_upload_enabled=False), "key", b"data")

    assert result is None
    assert calls == []


def test_returns_storage_uri_when_enabled(monkeypatch):
    monkeypatch.setattr(document_blob_store, "upload_document", lambda config, key, data: f"s3://arp-documents/{key}")

    result = document_blob_store.upload_document_if_enabled(_config(), "abc123", b"data")

    assert result == "s3://arp-documents/abc123"


def test_swallows_and_logs_exceptions(monkeypatch, caplog):
    def _raise(*a, **k):
        raise RuntimeError("bucket unreachable")

    monkeypatch.setattr(document_blob_store, "upload_document", _raise)

    with caplog.at_level("WARNING"):
        result = document_blob_store.upload_document_if_enabled(_config(), "abc123", b"data")  # must not raise

    assert result is None
    assert "abc123" in caplog.text


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
