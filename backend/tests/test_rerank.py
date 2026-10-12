import logging

from arp.retrieval import rerank
from arp.schemas.common import DocType, DocumentChunk


def chunk(chunk_id):
    return DocumentChunk(
        chunk_id=chunk_id, doc_id="d1", company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K,
        text=chunk_id, char_start=0, char_end=1,
    )


def _raising(exc):
    def scorer(query, texts):
        raise exc

    return scorer


def test_rerank_orders_by_score(monkeypatch):
    monkeypatch.setattr(rerank, "_unavailable", False)
    monkeypatch.setattr(rerank, "_score", lambda q, texts: [0.1, 0.9, 0.5])
    out = rerank.rerank("q", [chunk("a"), chunk("b"), chunk("c")], top_n=2)
    assert [c.chunk_id for c in out] == ["b", "c"]


def test_rerank_falls_back_when_model_unavailable(monkeypatch, caplog):
    calls = []

    def scorer(query, texts):
        calls.append(1)
        raise RuntimeError("no model")

    monkeypatch.setattr(rerank, "_score", scorer)
    monkeypatch.setattr(rerank, "_unavailable", False)
    with caplog.at_level(logging.WARNING, logger=rerank.__name__):
        first = rerank.rerank("q", [chunk("a"), chunk("b"), chunk("c")], top_n=2)
        second = rerank.rerank("q", [chunk("a"), chunk("b"), chunk("c")], top_n=2)
    assert [c.chunk_id for c in first] == ["a", "b"]
    assert [c.chunk_id for c in second] == ["a", "b"]
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1
    assert len(calls) == 1  # the failed load is not retried on the second call


def test_rerank_empty_input_skips_scorer(monkeypatch):
    monkeypatch.setattr(rerank, "_score", _raising(AssertionError("scorer called")))
    assert rerank.rerank("q", [], top_n=3) == []
