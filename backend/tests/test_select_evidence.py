from arp.retrieval.select_evidence import select_relevant_chunks
from arp.schemas.common import DocType, DocumentChunk


def _chunk(text, doc_type=DocType.ANNUAL_REPORT_10K, **kwargs):
    return DocumentChunk(doc_id="d1", company_id="c1", doc_type=doc_type, text=text, char_start=0, char_end=len(text), **kwargs)


def test_no_query_terms_returns_unranked_capped_list():
    chunks = [_chunk("alpha"), _chunk("beta"), _chunk("gamma")]
    result = select_relevant_chunks(chunks, [], max_chunks=2)
    assert result == chunks[:2]


def test_ranks_by_relevance_and_drops_zero_score_chunks():
    chunks = [
        _chunk("The company reported strong revenue growth in the automotive segment."),
        _chunk("Green capex increased significantly due to solar investments."),
        _chunk("Total employee headcount rose by five percent this year."),
        _chunk("Capital expenditure on renewable energy projects doubled."),
    ]
    result = select_relevant_chunks(chunks, ["green", "capex", "renewable"], max_chunks=10)
    texts = [c.text for c in result]
    assert texts[0] == chunks[1].text  # "Green capex..." should rank first
    assert chunks[2].text not in texts  # headcount chunk has zero term overlap, dropped


def test_doc_type_filter_excludes_other_types():
    chunks = [
        _chunk("green capex info", doc_type=DocType.ANNUAL_REPORT_10K),
        _chunk("green capex info", doc_type=DocType.SUSTAINABILITY_REPORT),
    ]
    result = select_relevant_chunks(chunks, ["capex"], doc_type_filter=[DocType.SUSTAINABILITY_REPORT])
    assert len(result) == 1
    assert result[0].doc_type == DocType.SUSTAINABILITY_REPORT


def test_require_hit_false_keeps_zero_score_chunks():
    chunks = [_chunk("totally unrelated text"), _chunk("green capex mentioned here")]
    result = select_relevant_chunks(chunks, ["capex"], require_hit=False)
    assert len(result) == 2


def test_fallback_to_all_when_nothing_matches():
    chunks = [_chunk("alpha text"), _chunk("beta text")]
    result = select_relevant_chunks(chunks, ["nonexistent-term-xyz"], fallback_to_all=True)
    assert len(result) == 2


def test_no_fallback_returns_empty_when_nothing_matches():
    chunks = [_chunk("alpha text"), _chunk("beta text")]
    result = select_relevant_chunks(chunks, ["nonexistent-term-xyz"], fallback_to_all=False)
    assert result == []


def test_empty_chunks_returns_empty():
    assert select_relevant_chunks([], ["anything"]) == []


def test_explicit_bm25_backend_matches_default_behavior():
    """retrieval_backend='bm25' is the default -- passing it explicitly
    must be byte-identical to omitting it, confirming this is a strict
    addition, not a behavior change."""
    chunks = [
        _chunk("The company reported strong revenue growth in the automotive segment."),
        _chunk("Green capex increased significantly due to solar investments."),
        _chunk("Capital expenditure on renewable energy projects doubled."),
    ]
    default = select_relevant_chunks(chunks, ["green", "capex", "renewable"], max_chunks=10)
    explicit = select_relevant_chunks(chunks, ["green", "capex", "renewable"], max_chunks=10, retrieval_backend="bm25")
    assert [c.chunk_id for c in default] == [c.chunk_id for c in explicit]


class _FakeOpenSearchClient:
    def __init__(self, scored_chunk_ids: dict[str, float]):
        self._scored = scored_chunk_ids

    def search(self, index, body):
        requested_ids = set(body["query"]["bool"]["filter"]["terms"]["chunk_id"])
        hits = [
            {"_source": {"chunk_id": cid}, "_score": score}
            for cid, score in sorted(self._scored.items(), key=lambda kv: kv[1], reverse=True)
            if cid in requested_ids
        ]
        return {"hits": {"hits": hits}}


def test_opensearch_backend_ranks_by_returned_score():
    chunks = [_chunk("alpha"), _chunk("beta"), _chunk("gamma")]
    client = _FakeOpenSearchClient({chunks[0].chunk_id: 0.5, chunks[1].chunk_id: 9.0, chunks[2].chunk_id: 0.0})

    result = select_relevant_chunks(
        chunks, ["query"], max_chunks=10, require_hit=False, retrieval_backend="opensearch", opensearch_client=client
    )

    assert [c.chunk_id for c in result] == [chunks[1].chunk_id, chunks[0].chunk_id, chunks[2].chunk_id]


def test_opensearch_backend_require_hit_drops_zero_score():
    chunks = [_chunk("alpha"), _chunk("beta")]
    client = _FakeOpenSearchClient({chunks[0].chunk_id: 0.0, chunks[1].chunk_id: 1.0})

    result = select_relevant_chunks(chunks, ["query"], retrieval_backend="opensearch", opensearch_client=client)

    assert [c.chunk_id for c in result] == [chunks[1].chunk_id]


def test_opensearch_backend_without_client_falls_back_to_bm25():
    """retrieval_backend='opensearch' with no client supplied must not
    error -- falls back to the default BM25 path, matching how
    hybrid_retrieval_enabled with no content_store already behaves."""
    chunks = [_chunk("green capex mentioned here"), _chunk("unrelated text")]
    result = select_relevant_chunks(chunks, ["capex"], retrieval_backend="opensearch", opensearch_client=None)
    assert len(result) == 1
    assert result[0].text == chunks[0].text
