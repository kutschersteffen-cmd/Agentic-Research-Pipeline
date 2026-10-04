import hashlib
import json
import time

import httpx

from arp.ingestion import edgar as edgar_module
from arp.ingestion.edgar import EdgarDocumentSource
from arp.ingestion.indexing_config import IndexingConfig
from arp.schemas.common import CompanyRef, DocType
from arp.storage.document_blob_store import LocalBlobStore
from arp.storage.document_store import DocumentContentStore, derive_doc_id


class _FailingClient:
    """Same shape as tests/test_source_fetch_cache.py's fake -- if a test
    using this reaches the network, .get() raises immediately rather than
    hanging in a sandboxed environment."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, *args, **kwargs):
        raise httpx.ConnectError("simulated network failure")


def _write_submissions_cache(cache_dir, cik10, submissions, fetched_at=None):
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {"_fetched_at": fetched_at if fetched_at is not None else time.time(), "data": submissions}
    (cache_dir / f"submissions_{cik10}.json").write_text(json.dumps(payload))


_SUBMISSIONS = {
    "filings": {
        "recent": {
            "form": ["10-K"],
            "accessionNumber": ["0000320193-24-000001"],
            "primaryDocument": ["aapl-10k.htm"],
            "filingDate": ["2024-01-01"],
        }
    }
}
_ACCESSION = "000032019324000001"
_PRIMARY_DOC = "aapl-10k.htm"


async def test_cached_submissions_and_filing_make_no_http_call(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    store = DocumentContentStore(tmp_path / "store")
    source = EdgarDocumentSource(user_agent="test-agent test@example.com", cache_dir=cache_dir, content_store=store)

    _write_submissions_cache(cache_dir, "0000320193", _SUBMISSIONS)
    content_key = hashlib.sha256(f"edgar:{_ACCESSION}/{_PRIMARY_DOC}".encode()).hexdigest()
    store.store(
        content_key,
        key_kind="edgar_accession",
        parser_version=edgar_module._edgar_parser_version(),
        source_suffix=".htm",
        byte_size=100,
        text="Cached filing text about green capex.",
        page_breaks=[],
    )

    monkeypatch.setattr(edgar_module.httpx, "AsyncClient", _FailingClient)

    company = CompanyRef(company_id="apple", name="Apple Inc.", cik="320193")
    docs = await source.fetch(company)

    assert len(docs) == 1
    assert docs[0].full_text == "Cached filing text about green capex."


async def test_expired_submissions_cache_is_refetched(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    store = DocumentContentStore(tmp_path / "store")
    source = EdgarDocumentSource(
        user_agent="test-agent test@example.com", cache_dir=cache_dir, content_store=store, submissions_ttl_hours=24.0
    )
    _write_submissions_cache(cache_dir, "0000320193", _SUBMISSIONS, fetched_at=time.time() - 25 * 3600)

    monkeypatch.setattr(edgar_module.httpx, "AsyncClient", _FailingClient)

    company = CompanyRef(company_id="apple", name="Apple Inc.", cik="320193")
    # The stale submissions cache is not used, so this must fall through
    # to a real network attempt -- which the fake client fails cleanly,
    # proving staleness (not just presence) gates the cache.
    try:
        await source.fetch(company)
        raised = False
    except httpx.ConnectError:
        raised = True
    assert raised


async def test_edgar_doc_id_is_stable_across_fetches(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    store = DocumentContentStore(tmp_path / "store")
    source = EdgarDocumentSource(user_agent="test-agent test@example.com", cache_dir=cache_dir, content_store=store)

    _write_submissions_cache(cache_dir, "0000320193", _SUBMISSIONS)
    content_key = hashlib.sha256(f"edgar:{_ACCESSION}/{_PRIMARY_DOC}".encode()).hexdigest()
    store.store(
        content_key,
        key_kind="edgar_accession",
        parser_version=edgar_module._edgar_parser_version(),
        source_suffix=".htm",
        byte_size=100,
        text="Filing text.",
        page_breaks=[],
    )
    monkeypatch.setattr(edgar_module.httpx, "AsyncClient", _FailingClient)

    company = CompanyRef(company_id="apple", name="Apple Inc.", cik="320193")
    first = await source.fetch(company)
    second = await source.fetch(company)

    assert first[0].doc_id == second[0].doc_id
    assert first[0].doc_id.startswith("doc_")


async def test_indexing_config_hooks_on_cache_hit_only_indexes_not_uploads(tmp_path, monkeypatch):
    """A parsed-content cache hit means the filing was already registered
    (and, if configured, already archived) on some earlier fetch -- so
    only the (idempotent, cheap-to-repeat) OpenSearch indexing hook fires
    again; there's no new raw_bytes to archive a second time."""
    index_calls = []
    upload_calls = []
    monkeypatch.setattr(
        "arp.retrieval.search_indexer.index_document_if_enabled", lambda config, **kwargs: index_calls.append(kwargs)
    )
    monkeypatch.setattr(
        "arp.storage.document_blob_store.blob_store_for", lambda config: type("S", (), {"exists": lambda self, k: True})()
    )
    monkeypatch.setattr(
        "arp.storage.document_blob_store.upload_or_fail", lambda *a, **k: upload_calls.append((a, k))
    )
    cache_dir = tmp_path / "cache"
    store = DocumentContentStore(tmp_path / "store")
    config = IndexingConfig(opensearch_url="http://localhost:9200", search_live_indexing_enabled=True)
    source = EdgarDocumentSource(user_agent="test-agent test@example.com", cache_dir=cache_dir, content_store=store, indexing_config=config)

    _write_submissions_cache(cache_dir, "0000320193", _SUBMISSIONS)
    content_key = hashlib.sha256(f"edgar:{_ACCESSION}/{_PRIMARY_DOC}".encode()).hexdigest()
    store.store(
        content_key, key_kind="edgar_accession", parser_version=edgar_module._edgar_parser_version(),
        source_suffix=".htm", byte_size=100, text="Cached filing text.", page_breaks=[],
    )
    monkeypatch.setattr(edgar_module.httpx, "AsyncClient", _FailingClient)
    # Already registered and archived on an earlier fetch.
    doc_id = derive_doc_id("apple", DocType.ANNUAL_REPORT_10K.value, content_key)
    store.register_document(
        doc_id=doc_id, company_id="apple", doc_type=DocType.ANNUAL_REPORT_10K.value, content_key=content_key,
        title="t", local_path=None, source_url="u",
    )
    store.set_storage_uri(doc_id, "file:///already")

    company = CompanyRef(company_id="apple", name="Apple Inc.", cik="320193")
    await source.fetch(company)

    assert len(index_calls) == 1
    assert index_calls[0]["full_text"] == "Cached filing text."
    assert upload_calls == []


async def test_indexing_config_hooks_on_fresh_fetch_archives_raw_bytes(tmp_path, monkeypatch):
    index_calls = []
    upload_calls = []
    monkeypatch.setattr(
        "arp.retrieval.search_indexer.index_document_if_enabled", lambda config, **kwargs: index_calls.append(kwargs)
    )
    monkeypatch.setattr("arp.storage.document_blob_store.blob_store_for", lambda config: None)
    monkeypatch.setattr(
        "arp.storage.document_blob_store.upload_or_fail",
        lambda store, content_key, data: upload_calls.append((content_key, data)) or "s3://arp-documents/fake",
    )
    cache_dir = tmp_path / "cache"
    store = DocumentContentStore(tmp_path / "store")
    config = IndexingConfig(opensearch_url="http://localhost:9200", search_live_indexing_enabled=True)
    source = EdgarDocumentSource(user_agent="test-agent test@example.com", cache_dir=cache_dir, content_store=store, indexing_config=config)
    _write_submissions_cache(cache_dir, "0000320193", _SUBMISSIONS)

    async def fake_get_and_extract_text(self, client, url):
        return "Freshly fetched filing text.", b"raw html bytes"

    monkeypatch.setattr(EdgarDocumentSource, "_get_and_extract_text", fake_get_and_extract_text)

    company = CompanyRef(company_id="apple", name="Apple Inc.", cik="320193")
    docs = await source.fetch(company)

    assert len(index_calls) == 1
    assert index_calls[0]["full_text"] == "Freshly fetched filing text."
    assert len(upload_calls) == 1
    assert upload_calls[0][1] == b"raw html bytes"
    assert store.resolve_document(docs[0].doc_id).storage_uri == "s3://arp-documents/fake"


async def test_unsafe_company_id_is_rejected_without_a_network_call(tmp_path, monkeypatch):
    store = DocumentContentStore(tmp_path / "store")
    source = EdgarDocumentSource(user_agent="test-agent test@example.com", cache_dir=tmp_path / "cache", content_store=store)
    monkeypatch.setattr(edgar_module.httpx, "AsyncClient", _FailingClient)

    company = CompanyRef(company_id="../../../../etc/cron.d", name="Bad", cik="320193")
    docs = await source.fetch(company)

    assert docs == []


async def test_no_content_store_behaves_exactly_as_before(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    source = EdgarDocumentSource(user_agent="test-agent test@example.com", cache_dir=cache_dir)
    _write_submissions_cache(cache_dir, "0000320193", _SUBMISSIONS)

    async def fake_get_and_extract_text(self, client, url):
        return "Fresh text every time, no cache.", b"raw bytes"

    monkeypatch.setattr(EdgarDocumentSource, "_get_and_extract_text", fake_get_and_extract_text)

    company = CompanyRef(company_id="apple", name="Apple Inc.", cik="320193")
    docs = await source.fetch(company)

    assert len(docs) == 1
    assert docs[0].full_text == "Fresh text every time, no cache."
    # random default doc_id, exactly like before this phase
    assert docs[0].doc_id.startswith("doc_")


_TWO = {
    "filings": {
        "recent": {
            "form": ["10-K", "DEF 14A"],
            "accessionNumber": ["0000320193-24-000001", "0000320193-24-000002"],
            "primaryDocument": ["a.htm", "b.htm"],
            "filingDate": ["2024-01-01", "2024-02-01"],
        }
    }
}


def _setup(tmp_path, monkeypatch, submissions, blobs):
    cache_dir = tmp_path / "cache"
    store = DocumentContentStore(tmp_path / "store")
    config = IndexingConfig(blob_store_dir=blobs)
    source = EdgarDocumentSource(user_agent="t t@example.com", cache_dir=cache_dir, content_store=store, indexing_config=config)
    _write_submissions_cache(cache_dir, "0000320193", submissions)

    async def fake(self, client, url):
        return f"text of {url}", f"bytes of {url}".encode()

    monkeypatch.setattr(EdgarDocumentSource, "_get_and_extract_text", fake)
    monkeypatch.setattr(edgar_module.httpx, "AsyncClient", lambda *a, **k: _FailingClient())
    return source, store


COMPANY = CompanyRef(company_id="apple", name="Apple Inc.", cik="320193")


async def test_edgar_real_store_keys_blob_by_sha256_of_bytes(tmp_path, monkeypatch):
    source, store = _setup(tmp_path, monkeypatch, _SUBMISSIONS, tmp_path / "blobs")
    (doc,) = await source.fetch(COMPANY)
    raw = f"bytes of {doc.source_url}".encode()
    key = hashlib.sha256(raw).hexdigest()
    assert LocalBlobStore(tmp_path / "blobs").get(key) == raw
    assert store.resolve_document(doc.doc_id).storage_uri.startswith("file://")


async def test_edgar_store_failure_then_retry_archives_before_returning(tmp_path, monkeypatch):
    blobs = tmp_path / "blobs"
    blobs.write_text("not a dir")  # store fails on the first fetch
    source, store = _setup(tmp_path, monkeypatch, _SUBMISSIONS, blobs)
    assert await source.fetch(COMPANY) == []
    blobs.unlink()
    (doc,) = await source.fetch(COMPANY)  # parse cache hit, but no blob yet -> re-fetch and archive
    assert store.resolve_document(doc.doc_id).storage_uri.startswith("file://")


async def test_edgar_one_failing_filing_does_not_abort_the_other(tmp_path, monkeypatch):
    source, _ = _setup(tmp_path, monkeypatch, _TWO, tmp_path / "blobs")
    from arp.storage import document_blob_store as dbs

    orig = dbs.upload_or_fail

    def flaky(store, key, data):
        if b"b.htm" in data:
            raise dbs.CaptureStoreError("boom")
        return orig(store, key, data)

    monkeypatch.setattr(dbs, "upload_or_fail", flaky)
    docs = await source.fetch(COMPANY)
    assert [d.title for d in docs] == ["Apple Inc. 10-K (2024-01-01)"]


async def test_edgar_lost_blob_is_archived_again(tmp_path, monkeypatch):
    # The registry still names a storage_uri, but the blob itself is gone: re-fetch and re-archive.
    source, store = _setup(tmp_path, monkeypatch, _SUBMISSIONS, tmp_path / "blobs")
    (doc,) = await source.fetch(COMPANY)
    key = hashlib.sha256(f"bytes of {doc.source_url}".encode()).hexdigest()
    blob = tmp_path / "blobs" / key[:2] / key
    blob.unlink()
    (doc,) = await source.fetch(COMPANY)
    assert blob.read_bytes() == f"bytes of {doc.source_url}".encode()
