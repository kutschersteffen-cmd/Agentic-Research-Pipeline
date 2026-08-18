from llama_index.retrievers.bm25 import BM25Retriever

from arp.retrieval import index_cache as index_cache_module
from arp.retrieval.select_evidence import select_relevant_chunks
from arp.schemas.common import DocType, DocumentChunk


def setup_function():
    index_cache_module.clear_index_cache()


def _chunk(chunk_id, text, doc_type=DocType.ANNUAL_REPORT_10K):
    return DocumentChunk(
        chunk_id=chunk_id, doc_id="d1", company_id="c1", doc_type=doc_type, text=text, char_start=0, char_end=len(text)
    )


def test_second_selection_over_the_same_candidates_reuses_the_built_index(monkeypatch):
    calls = []
    original = BM25Retriever.from_defaults

    def counting_from_defaults(cls, *args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(BM25Retriever, "from_defaults", classmethod(counting_from_defaults))

    chunks = [
        _chunk("c1", "Green capex increased significantly due to solar investments."),
        _chunk("c2", "Total employee headcount rose by five percent this year."),
        _chunk("c3", "Capital expenditure on renewable energy projects doubled."),
    ]

    select_relevant_chunks(chunks, ["capex"])
    select_relevant_chunks(chunks, ["renewable"])  # different field, same corpus

    assert len(calls) == 1


def test_different_candidate_sets_are_separate_cache_entries(monkeypatch):
    calls = []
    original = BM25Retriever.from_defaults

    def counting_from_defaults(cls, *args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(BM25Retriever, "from_defaults", classmethod(counting_from_defaults))

    a = [_chunk("a1", "green capex text"), _chunk("a2", "solar power text")]
    b = [_chunk("b1", "green capex text"), _chunk("b2", "solar power text")]

    select_relevant_chunks(a, ["capex"])
    select_relevant_chunks(b, ["capex"])

    assert len(calls) == 2


def test_doc_type_filter_changes_the_candidate_set_and_the_cache_entry(monkeypatch):
    calls = []
    original = BM25Retriever.from_defaults

    def counting_from_defaults(cls, *args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(BM25Retriever, "from_defaults", classmethod(counting_from_defaults))

    chunks = [
        _chunk("c1", "green capex info", doc_type=DocType.ANNUAL_REPORT_10K),
        _chunk("c2", "green capex info", doc_type=DocType.SUSTAINABILITY_REPORT),
    ]

    select_relevant_chunks(chunks, ["capex"], doc_type_filter=[DocType.SUSTAINABILITY_REPORT])
    select_relevant_chunks(chunks, ["capex"])  # unfiltered -- a different candidate set

    assert len(calls) == 2


def test_cache_reuse_does_not_change_selection_results():
    chunks = [
        _chunk("c1", "The company reported strong revenue growth in the automotive segment."),
        _chunk("c2", "Green capex increased significantly due to solar investments."),
        _chunk("c3", "Total employee headcount rose by five percent this year."),
        _chunk("c4", "Capital expenditure on renewable energy projects doubled."),
    ]

    first = select_relevant_chunks(chunks, ["green", "capex", "renewable"], max_chunks=10)
    index_cache_module.clear_index_cache()  # force a fresh build, no cache reuse
    second = select_relevant_chunks(chunks, ["green", "capex", "renewable"], max_chunks=10)

    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]


def test_lru_eviction_bounds_the_cache_and_reused_index_still_selects_correctly():
    cache = index_cache_module.get_index_cache()
    for i in range(cache._max_entries + 5):
        chunks = [_chunk(f"c{i}_1", "green capex"), _chunk(f"c{i}_2", f"unique marker {i}")]
        select_relevant_chunks(chunks, ["capex"])

    assert cache.stats()["entries"] <= cache._max_entries

    chunks = [_chunk("final_1", "green capex here"), _chunk("final_2", "unrelated content")]
    result = select_relevant_chunks(chunks, ["capex"])
    assert [c.chunk_id for c in result] == ["final_1"]
