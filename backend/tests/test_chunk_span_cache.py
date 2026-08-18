import threading
import time

from arp.ingestion import parsing
from arp.ingestion.chunk_spans import clear_span_cache
from arp.ingestion.parsing import chunk_document
from arp.schemas.common import DocType, SourceDocument


def setup_function():
    clear_span_cache()


def _doc(text, doc_type=DocType.ANNUAL_REPORT_10K, doc_id="doc_a"):
    return SourceDocument(doc_id=doc_id, company_id="c1", doc_type=doc_type, title="t", full_text=text)


_TEXT = ("Paragraph about green capex investments and solar power.\n\n" * 30) + "Final paragraph here."


def test_second_call_reuses_spans_without_resplitting(monkeypatch):
    calls = []
    original = parsing._sentence_aware_split

    def counting_split(text, chunk_chars, overlap_chars):
        calls.append(1)
        return original(text, chunk_chars, overlap_chars)

    monkeypatch.setattr(parsing, "_sentence_aware_split", counting_split)

    doc = _doc(_TEXT)
    chunk_document(doc, chunk_chars=500, overlap_chars=50, keywords=["capex"])
    chunk_document(doc, chunk_chars=500, overlap_chars=50, keywords=["capex"])

    assert len(calls) == 1


def test_different_keywords_yield_identical_spans_and_different_hits():
    doc = _doc(_TEXT)
    a = chunk_document(doc, chunk_chars=500, overlap_chars=50, keywords=["capex"])
    b = chunk_document(doc, chunk_chars=500, overlap_chars=50, keywords=["solar"])

    assert [(c.char_start, c.char_end) for c in a] == [(c.char_start, c.char_end) for c in b]
    assert [c.section for c in a] == [c.section for c in b]
    assert any(c.keyword_hits for c in a)
    assert any(c.keyword_hits for c in b)
    assert [c.keyword_hits for c in a] != [c.keyword_hits for c in b]


def test_different_chunk_chars_is_a_separate_entry(monkeypatch):
    calls = []
    original = parsing._sentence_aware_split

    def counting_split(text, chunk_chars, overlap_chars):
        calls.append(chunk_chars)
        return original(text, chunk_chars, overlap_chars)

    monkeypatch.setattr(parsing, "_sentence_aware_split", counting_split)

    doc = _doc(_TEXT)
    chunk_document(doc, chunk_chars=500, overlap_chars=50)
    chunk_document(doc, chunk_chars=600, overlap_chars=50)

    assert calls == [500, 600]


def test_transcript_vs_report_doc_type_are_separate_entries(monkeypatch):
    calls = []
    original = parsing._sentence_aware_split

    def counting_split(text, chunk_chars, overlap_chars):
        calls.append(1)
        return original(text, chunk_chars, overlap_chars)

    monkeypatch.setattr(parsing, "_sentence_aware_split", counting_split)

    report = _doc(_TEXT, doc_type=DocType.ANNUAL_REPORT_10K)
    transcript = _doc(_TEXT, doc_type=DocType.EARNINGS_TRANSCRIPT)
    chunk_document(report, chunk_chars=500, overlap_chars=50)
    chunk_document(transcript, chunk_chars=500, overlap_chars=50)

    assert len(calls) == 2


def test_changed_text_length_is_a_miss(monkeypatch):
    calls = []
    original = parsing._sentence_aware_split

    def counting_split(text, chunk_chars, overlap_chars):
        calls.append(1)
        return original(text, chunk_chars, overlap_chars)

    monkeypatch.setattr(parsing, "_sentence_aware_split", counting_split)

    chunk_document(_doc(_TEXT), chunk_chars=500, overlap_chars=50)
    chunk_document(_doc(_TEXT + " more text appended here."), chunk_chars=500, overlap_chars=50)

    assert len(calls) == 2


def test_lru_eviction_bounds_the_cache_and_results_stay_correct():
    from arp.ingestion.chunk_spans import get_span_cache

    cache = get_span_cache()
    for i in range(cache._max_entries + 20):
        doc = _doc(_TEXT + f"\n\nunique marker {i}", doc_id=f"doc_{i}")
        chunk_document(doc, chunk_chars=500, overlap_chars=50)

    assert cache.stats()["entries"] <= cache._max_entries

    # a fresh call after eviction still produces correct, fully-covering chunks
    doc = _doc(_TEXT, doc_id="doc_final")
    chunks = chunk_document(doc, chunk_chars=500, overlap_chars=50)
    covered = [False] * len(_TEXT)
    for c in chunks:
        for i in range(c.char_start, c.char_end):
            covered[i] = True
    assert all(covered)


def test_returned_chunks_are_not_aliased_across_calls():
    doc = _doc(_TEXT)
    a = chunk_document(doc, chunk_chars=500, overlap_chars=50, keywords=["capex"])
    b = chunk_document(doc, chunk_chars=500, overlap_chars=50, keywords=["capex"])

    assert a is not b
    assert a[0] is not b[0]
    a[0].keyword_hits.append("mutated")
    assert "mutated" not in b[0].keyword_hits


def test_concurrent_calls_agree(monkeypatch):
    original = parsing._sentence_aware_split

    def slow_split(text, chunk_chars, overlap_chars):
        time.sleep(0.02)
        return original(text, chunk_chars, overlap_chars)

    monkeypatch.setattr(parsing, "_sentence_aware_split", slow_split)

    doc = _doc(_TEXT)
    results: list[list] = []
    errors: list[Exception] = []

    def worker():
        try:
            results.append(chunk_document(doc, chunk_chars=500, overlap_chars=50, keywords=["capex"]))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(results) == 10
    first = [(c.char_start, c.char_end) for c in results[0]]
    for r in results[1:]:
        assert [(c.char_start, c.char_end) for c in r] == first
