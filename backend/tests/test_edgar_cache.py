import hashlib
import json
import time

import httpx

from arp.ingestion import edgar as edgar_module
from arp.ingestion.edgar import EdgarDocumentSource
from arp.schemas.common import CompanyRef
from arp.storage.document_store import DocumentContentStore


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
    content_key = hashlib.sha256(f"edgar:{_ACCESSION}/{_PRIMARY_DOC}".encode("utf-8")).hexdigest()
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
    content_key = hashlib.sha256(f"edgar:{_ACCESSION}/{_PRIMARY_DOC}".encode("utf-8")).hexdigest()
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
        return "Fresh text every time, no cache."

    monkeypatch.setattr(EdgarDocumentSource, "_get_and_extract_text", fake_get_and_extract_text)

    company = CompanyRef(company_id="apple", name="Apple Inc.", cik="320193")
    docs = await source.fetch(company)

    assert len(docs) == 1
    assert docs[0].full_text == "Fresh text every time, no cache."
    # random default doc_id, exactly like before this phase
    assert docs[0].doc_id.startswith("doc_")
