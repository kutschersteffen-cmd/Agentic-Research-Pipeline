from __future__ import annotations

import asyncio
import hashlib

import httpx
import pytest

from arp.discovery import downloader
from arp.discovery.crawler import CandidateDocumentLink
from arp.ingestion.indexing_config import IndexingConfig
from arp.ingestion.local_files import LocalFileDocumentSource
from arp.schemas.common import CompanyRef, DocType
from arp.storage.document_blob_store import CaptureStoreError, LocalBlobStore, upload_or_fail
from arp.storage.document_store import DocumentContentStore
from arp.storage.jsonl_io import read_jsonl

ACME = CompanyRef(company_id="acme", name="Acme")
BODY = b"%PDF-1.4 fake report body"


@pytest.fixture(autouse=True)
def _no_ssrf(monkeypatch):
    async def noop(request):
        return None

    monkeypatch.setattr(downloader, "ssrf_guard_request_hook", noop)


def _candidate(url="https://acme.example/r.pdf"):
    return CandidateDocumentLink(url=url, doc_type=DocType.SUSTAINABILITY_REPORT, link_text="r")


def _run(documents_dir, store, handler):
    return asyncio.run(
        downloader.download_documents(
            ACME, [_candidate()], documents_dir, "ua", store=store, transport=httpx.MockTransport(handler)
        )
    )


class _FailingStore:
    def put(self, key, data):
        raise OSError("disk full")

    def get(self, key):
        raise OSError("nope")

    def exists(self, key):
        return False


def test_failed_upload_leaves_document_uncollected(tmp_path):
    docs = _run(tmp_path, _FailingStore(), lambda req: httpx.Response(200, content=BODY))
    assert docs == []
    assert not (tmp_path / "acme").exists() or not [p for p in (tmp_path / "acme").rglob("*") if p.is_file()]
    rows = read_jsonl(tmp_path / downloader.CAPTURE_LOG)
    assert len(rows) == 1
    assert rows[0]["collected"] is False
    assert rows[0]["error"]


def test_hash_mismatch_on_reread_fails(tmp_path):
    class Lying(LocalBlobStore):
        def get(self, key):
            return b"other bytes"

    key = hashlib.sha256(BODY).hexdigest()
    with pytest.raises(CaptureStoreError):
        upload_or_fail(Lying(tmp_path), key, BODY)


def test_capture_record_fields(tmp_path):
    def handler(req):
        if req.url.path == "/r.pdf":
            return httpx.Response(301, headers={"location": "https://acme.example/final.pdf"})
        return httpx.Response(
            200, content=BODY, headers={"content-type": "application/pdf", "set-cookie": "a=b", "etag": "x"}
        )

    docs = _run(tmp_path / "docs", LocalBlobStore(tmp_path / "blobs"), handler)
    assert len(docs) == 1
    (row,) = read_jsonl(tmp_path / "docs" / downloader.CAPTURE_LOG)
    assert row["url_chain"] == ["https://acme.example/r.pdf", "https://acme.example/final.pdf"]
    assert row["status"] == 200
    assert "set-cookie" not in row["headers"]
    assert row["content_key"] == hashlib.sha256(BODY).hexdigest()
    assert row["storage_uri"].startswith("file://")
    assert row["trigger"] == "discovery"
    assert row["rights_tag"] == "public_disclosure"
    assert row["collected"] is True
    assert docs[0].capture_id == row["capture_id"]
    assert downloader.latest_capture(tmp_path / "docs", row["content_key"]).capture_id == row["capture_id"]


def test_upload_or_fail_skips_put_when_present(tmp_path):
    calls = []

    class Counting(LocalBlobStore):
        def put(self, key, data):
            calls.append(key)
            return super().put(key, data)

    store = Counting(tmp_path)
    key = hashlib.sha256(BODY).hexdigest()
    first = upload_or_fail(store, key, BODY)
    second = upload_or_fail(store, key, BODY)
    assert calls == [key]
    assert first == second


def test_local_files_skips_file_when_archive_fails(tmp_path):
    folder = tmp_path / "docs" / "acme" / DocType.ANNUAL_REPORT_10K.value
    folder.mkdir(parents=True)
    (folder / "report.txt").write_text("Some disclosure text about green capex.")
    not_a_dir = tmp_path / "blobfile"
    not_a_dir.write_text("x")
    config = IndexingConfig(blob_store_dir=not_a_dir)
    source = LocalFileDocumentSource(
        tmp_path / "docs", content_store=DocumentContentStore(tmp_path / "store"), indexing_config=config
    )
    assert asyncio.run(source.fetch(ACME)) == []


def test_upload_or_fail_rejects_stored_bytes_with_other_hash(tmp_path):
    class Corrupting(LocalBlobStore):
        def put(self, key, data):
            return super().put(key, data + b"x")

    with pytest.raises(CaptureStoreError):
        upload_or_fail(Corrupting(tmp_path), hashlib.sha256(BODY).hexdigest(), BODY)


def test_local_files_real_store_success(tmp_path):
    folder = tmp_path / "docs" / "acme" / DocType.ANNUAL_REPORT_10K.value
    folder.mkdir(parents=True)
    (folder / "report.txt").write_text("Some disclosure text about green capex.")
    blobs = tmp_path / "blobs"
    store = DocumentContentStore(tmp_path / "store")
    source = LocalFileDocumentSource(tmp_path / "docs", content_store=store, indexing_config=IndexingConfig(blob_store_dir=blobs))
    (doc,) = asyncio.run(source.fetch(ACME))
    key = hashlib.sha256(b"Some disclosure text about green capex.").hexdigest()
    assert LocalBlobStore(blobs).exists(key)
    assert store.resolve_document(doc.doc_id).storage_uri.startswith("file://")
