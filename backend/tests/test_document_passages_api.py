"""GET /api/documents/cache/{row_id}/passages: how a cached text is cut into passages (passage-view spec)."""

import bisect

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_document_content_store
from arp.api.main import app
from arp.ingestion.parsing import chunk_document
from arp.schemas.common import DocType, SourceDocument
from arp.storage.document_store import DocumentContentStore
from tests.postgres_helpers import pg_dsn

pytestmark = pytest.mark.usefixtures("pg")

# T1: 3 PDF pages, ~9,000 characters, "# Risk" at offset 0, page 3 empty after stripping
_P1 = "# Risk\n\n" + "Climate risk is material to the business. " * 100
_P2 = "Emissions fell by ten percent in the year. " * 100
T1 = _P1 + _P2 + "  \n\n "
T1_BREAKS = [len(_P1), len(_P1) + len(_P2)]
# T3: transcript, short turns, so every passage start has a speaker line within detect_speaker's window
T3 = "".join(f"{name}:\nWe grew revenue across all regions this quarter, said {name}. Margins held up well.\n\n"
             for _ in range(60) for name in ("Jane Doe", "John Roe"))


@pytest.fixture
def store(tmp_path):
    s = DocumentContentStore(tmp_path / "store", dsn=pg_dsn())
    app.dependency_overrides[get_document_content_store] = lambda: s
    yield s
    app.dependency_overrides.pop(get_document_content_store, None)


def _cache(store, key, body, breaks=(), doc_type=None):
    store.store(key, key_kind="file", parser_version="p", source_suffix=".txt", byte_size=len(body), text=body,
                page_breaks=list(breaks))
    if doc_type:
        store.register_document(doc_id=f"doc_{key}", company_id="acme", doc_type=doc_type, content_key=key,
                                title="T", local_path=None, source_url=None)
    rows, _ = store.list_cached_content(0, 500)
    return next(r["id"] for r in rows if r["content_key"] == key)


def _get(row_id):
    return TestClient(app).get(f"/api/documents/cache/{row_id}/passages")


def _expected(body, doc_type):
    return [(c.char_start, c.char_end) for c in chunk_document(SourceDocument(company_id="x", doc_type=doc_type, title="", full_text=body))]


def test_passages_match_chunk_document(store):  # AC-1, AC-2, AC-3
    body = _get(_cache(store, "t1", T1, T1_BREAKS, "10-K")).json()
    assert [(p["char_start"], p["char_end"]) for p in body["passages"]] == _expected(T1, DocType.ANNUAL_REPORT_10K)
    assert [p["index"] for p in body["passages"]] == list(range(1, len(body["passages"]) + 1))
    assert all(p["chars"] == p["char_end"] - p["char_start"] for p in body["passages"])
    assert (body["chunk_chars"], body["overlap_chars"]) == (3500, 300)


def test_pages(store):  # AC-4, AC-5
    body = _get(_cache(store, "t1p", T1, T1_BREAKS, "10-K")).json()
    for p in body["passages"]:
        assert p["page_start"] == bisect.bisect_right(T1_BREAKS, p["char_start"]) + 1
        assert p["page_end"] == bisect.bisect_right(T1_BREAKS, p["char_end"] - 1) + 1
    assert body["page_count"] == 3
    assert body["summary"]["empty_pages"] == [3]


def test_section_and_summary_counts(store):  # AC-6, AC-7
    body = _get(_cache(store, "t1s", T1, T1_BREAKS, "10-K")).json()
    assert body["passages"][0]["section"] == "Risk"
    assert body["summary"]["short"] == sum(p["chars"] < 200 for p in body["passages"])
    assert body["summary"]["no_section"] == sum(p["section"] is None for p in body["passages"])


def test_no_page_breaks(store):  # AC-8
    body = _get(_cache(store, "t2", T1, (), "10-K")).json()
    assert all(p["page_start"] is None and p["page_end"] is None for p in body["passages"])
    assert body["page_count"] is None and body["summary"]["empty_pages"] == []


def test_transcript_speakers(store):  # AC-9, AC-26, AC-27
    from arp.ingestion.parsing import detect_speaker

    body = _get(_cache(store, "t3", T3, (), "earnings_transcript")).json()
    assert len(body["passages"]) > 1
    assert [p["speaker"] for p in body["passages"]] == [detect_speaker(T3, p["char_start"]) for p in body["passages"]]
    assert body["passages"][1]["speaker"] in {"Jane Doe", "John Roe"}
    assert all(p["section"] is None for p in body["passages"])
    assert body["summary"]["no_section"] == 0


def test_unregistered_row_uses_10k(store):  # AC-10
    r = _get(_cache(store, "t_unreg", T1))
    assert r.status_code == 200
    assert [(p["char_start"], p["char_end"]) for p in r.json()["passages"]] == _expected(T1, DocType.ANNUAL_REPORT_10K)


def test_missing_row(store):  # AC-11
    r = _get(987654321)
    assert (r.status_code, r.json()["detail"]) == (404, "Cached document not found")


def test_nothing_is_stored(store):  # AC-31
    row = _cache(store, "t_count", T1, T1_BREAKS, "10-K")

    def counts():
        return store.list_cached_content(0, 1)[1], len(store.list_all_documents())

    before = counts()
    _get(row), _get(row)
    assert counts() == before


def test_cache_endpoints_keep_their_keys(store):  # AC-32
    row = _cache(store, "t_keys", T1, T1_BREAKS, "10-K")
    client = TestClient(app)
    assert set(client.get("/api/documents/cache").json()) == {"total", "documents"}
    assert set(client.get(f"/api/documents/cache/{row}").json()) == {
        "content_key", "company_id", "doc_type", "title", "filename", "full_text", "page_breaks", "text_sha256",
    }
