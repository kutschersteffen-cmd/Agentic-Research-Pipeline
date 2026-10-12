from __future__ import annotations

import logging

from arp.schemas.common import DocumentChunk

logger = logging.getLogger(__name__)

# Multilingual (EN/DE) cross-encoder, the smallest multilingual one fastembed
# lists (~0.57GB INT8 ONNX); the smaller ms-marco/jina-tiny models are English-only.
RERANK_MODEL_NAME = "BAAI/bge-reranker-v2-m3-int8"

_model = None
_warned = False


def _get_model():
    global _model
    if _model is None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        _model = TextCrossEncoder(model_name=RERANK_MODEL_NAME)
    return _model


def _score(query: str, texts: list[str]) -> list[float]:
    return [float(s) for s in _get_model().rerank(query, texts)]


def rerank(query: str, chunks: list[DocumentChunk], top_n: int) -> list[DocumentChunk]:
    """At most `top_n` of `chunks`, best cross-encoder score first. If the
    model can't load or score, returns `chunks[:top_n]` unchanged and warns
    once per process -- reranking is a precision boost, never a hard dependency."""
    global _warned
    if not chunks:
        return []
    try:
        scores = _score(query, [c.text for c in chunks])
    except Exception as exc:
        if not _warned:
            _warned = True
            logger.warning("Reranker unavailable (%s: %s); keeping retrieval order.", type(exc).__name__, exc)
        return chunks[:top_n]
    order = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)  # stable on ties
    return [chunks[i] for i in order[:top_n]]
