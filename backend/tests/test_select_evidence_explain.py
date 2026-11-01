"""select_relevant_chunks' `explain`: why these chunks were picked (why-this-evidence spec, AC-1 to AC-13, AC-38 to AC-41)."""

import pytest

from arp.retrieval import rerank, select_evidence
from arp.retrieval.select_evidence import select_relevant_chunks
from arp.schemas.common import DocType, DocumentChunk


def _chunk(text):
    return DocumentChunk(doc_id="d1", company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, text=text, char_start=0, char_end=len(text))


# F1: 20 chunks, 10 with a hit of decreasing strength, 10 without
F1 = [_chunk(" ".join(["capex"] * (11 - i)) + f" filler {i}") for i in range(10)] + [_chunk(f"unrelated text {i}") for i in range(10)]


def _f1(**kw):
    explain: dict = {}
    out = select_relevant_chunks(F1, ["capex"], max_chunks=5, explain=explain, **kw)
    return out, explain


class _FakeOpenSearchClient:
    def search(self, index, body):
        ids = body["query"]["bool"]["filter"]["terms"]["chunk_id"]
        return {"hits": {"hits": [{"_source": {"chunk_id": cid}, "_score": float(20 - i)} for i, cid in enumerate(ids[:10])]}}


@pytest.fixture
def scorer(monkeypatch):
    monkeypatch.setattr(rerank, "_unavailable", False)
    monkeypatch.setattr(rerank.compute_client, "models_configured", lambda: False)
    monkeypatch.setattr(rerank, "_score", lambda q, texts: [float(i) for i in range(len(texts))])  # reverses the order


@pytest.fixture
def vectors(monkeypatch):
    monkeypatch.setattr(select_evidence, "_vector_ranking", lambda candidates, q, store: [c.chunk_id for c in reversed(candidates)])


def test_explain_does_not_change_the_result():  # AC-1
    out, _ = _f1()
    assert out == select_relevant_chunks(F1, ["capex"], max_chunks=5)


def test_bm25_method_and_counts():  # AC-2, AC-3, AC-38
    _, ex = _f1()
    assert ex["method"] == "bm25"
    assert ex["reranked"] is False
    assert ex["candidates"] == 20


def test_bm25_scores_fall_in_return_order():  # AC-4
    out, ex = _f1()
    values = [ex["scores"][c.chunk_id]["bm25"] for c in out]
    assert all(v > 0 for v in values)
    assert values == sorted(values, reverse=True)


def test_near_misses_are_the_next_three():  # AC-5
    full = select_relevant_chunks(F1, ["capex"], max_chunks=8)
    _, ex = _f1()
    assert ex["near_misses"] == [c.chunk_id for c in full[5:8]]


def test_hybrid(vectors):  # AC-6, AC-7
    out, ex = _f1(hybrid_retrieval_enabled=True, content_store=object())
    assert ex["method"] == "hybrid"
    for c in out:
        assert isinstance(ex["scores"][c.chunk_id]["rrf"], float)
        assert ex["scores"][c.chunk_id]["vector_rank"] >= 1


def test_reranked(scorer):  # AC-8, AC-39
    out, ex = _f1(rerank_candidates=10)
    assert ex["reranked"] is True
    assert all(isinstance(ex["scores"][c.chunk_id]["rerank"], float) for c in out)


def test_reranked_even_when_order_is_kept(monkeypatch, scorer):  # AC-9
    monkeypatch.setattr(rerank, "_score", lambda q, texts: [float(-i) for i in range(len(texts))])
    _, ex = _f1(rerank_candidates=10)
    assert ex["reranked"] is True


def test_opensearch():  # AC-10
    _, ex = _f1(retrieval_backend="opensearch", opensearch_client=_FakeOpenSearchClient())
    assert ex["method"] == "opensearch"


def test_opensearch_hybrid(vectors):  # AC-11
    _, ex = _f1(retrieval_backend="opensearch", opensearch_client=_FakeOpenSearchClient(),
                hybrid_retrieval_enabled=True, content_store=object())
    assert ex["method"] == "opensearch_hybrid"


def test_unranked_fallback():  # AC-12, AC-40
    explain: dict = {}
    out = select_relevant_chunks(F1[10:], ["capex"], max_chunks=5, fallback_to_all=True, explain=explain)
    assert explain["method"] == "unranked"
    assert all("bm25" not in explain["scores"].get(c.chunk_id, {}) for c in out)


def test_no_query_terms():  # AC-13, AC-41
    explain: dict = {}
    select_relevant_chunks(F1, [], max_chunks=5, explain=explain)
    assert explain["method"] == "none"
    assert explain["scores"] == {}
