import numpy as np

from arp.retrieval import embeddings as embeddings_module
from arp.retrieval.select_evidence import _rrf_fuse, select_relevant_chunks
from arp.schemas.common import DocType, DocumentChunk
from arp.storage.document_store import DocumentContentStore


def _chunk(chunk_id, text, doc_type=DocType.ANNUAL_REPORT_10K):
    return DocumentChunk(
        chunk_id=chunk_id, doc_id="d1", company_id="c1", doc_type=doc_type, text=text, char_start=0, char_end=len(text)
    )


def _fake_embed(vectors_by_text):
    def embed_texts(texts):
        return np.array([vectors_by_text[t] for t in texts], dtype=np.float32)

    return embed_texts


def test_rrf_fuse_favors_items_ranked_high_in_multiple_lists():
    fused = _rrf_fuse([["a", "b", "c"], ["b", "a", "c"]])
    assert fused[0] in ("a", "b")
    assert fused[-1] == "c"


def test_rrf_fuse_includes_items_present_in_only_one_ranking():
    fused = _rrf_fuse([["a", "b"], ["c"]])
    assert set(fused) == {"a", "b", "c"}


def test_hybrid_flag_off_is_identical_to_bm25_only():
    chunks = [_chunk("c1", "green capex info"), _chunk("c2", "unrelated text")]
    default = select_relevant_chunks(chunks, ["capex"])
    explicit_off = select_relevant_chunks(chunks, ["capex"], hybrid_retrieval_enabled=False, content_store=None)
    assert [c.chunk_id for c in default] == [c.chunk_id for c in explicit_off]


def test_hybrid_enabled_without_a_content_store_falls_back_to_bm25_only():
    chunks = [_chunk("c1", "green capex info"), _chunk("c2", "unrelated text")]
    bm25_only = select_relevant_chunks(chunks, ["capex"])
    hybrid_no_store = select_relevant_chunks(chunks, ["capex"], hybrid_retrieval_enabled=True, content_store=None)
    assert [c.chunk_id for c in bm25_only] == [c.chunk_id for c in hybrid_no_store]


def test_hybrid_surfaces_a_semantically_close_chunk_with_zero_keyword_overlap(tmp_path, monkeypatch):
    chunks = [
        _chunk("kw", "green capex mentioned here explicitly"),
        _chunk("semantic", "the e-mobility transition accelerated this year"),
        _chunk("noise", "unrelated administrative filing text"),
    ]
    vectors = {
        "green capex mentioned here explicitly": [1.0, 0.0],
        "the e-mobility transition accelerated this year": [0.0, 1.0],
        "unrelated administrative filing text": [-1.0, -1.0],
        "electrification": [0.0, 1.0],  # query embeds identical to the "semantic" chunk
    }
    monkeypatch.setattr(embeddings_module, "embed_texts", _fake_embed(vectors))
    store = DocumentContentStore(tmp_path / "store")

    # None of these chunks literally contain "electrification", so BM25's
    # require_hit filter drops every chunk -- the fused ranking is driven
    # entirely by the vector axis, the exact gap hybrid retrieval exists
    # to close.
    result = select_relevant_chunks(
        chunks, ["electrification"], require_hit=True, hybrid_retrieval_enabled=True, content_store=store
    )

    ids = [c.chunk_id for c in result]
    assert ids[0] == "semantic"


def test_hybrid_reuses_cached_chunk_embeddings_across_calls(tmp_path, monkeypatch):
    chunks = [_chunk("c1", "alpha text"), _chunk("c2", "beta text")]
    calls: list[list[str]] = []
    vectors = {
        "alpha text": [1.0, 0.0],
        "beta text": [0.0, 1.0],
        "query one": [1.0, 0.0],
        "query two": [1.0, 0.0],
    }

    def counting_embed(texts):
        calls.append(list(texts))
        return np.array([vectors[t] for t in texts], dtype=np.float32)

    monkeypatch.setattr(embeddings_module, "embed_texts", counting_embed)
    store = DocumentContentStore(tmp_path / "store")

    select_relevant_chunks(chunks, ["query", "one"], hybrid_retrieval_enabled=True, content_store=store)
    select_relevant_chunks(chunks, ["query", "two"], hybrid_retrieval_enabled=True, content_store=store)

    chunk_text_calls = [t for call in calls for t in call if t in ("alpha text", "beta text")]
    assert sorted(chunk_text_calls) == sorted(["alpha text", "beta text"])  # embedded once each, not per-call
    assert store.stats()["cached_embeddings"] == 2
