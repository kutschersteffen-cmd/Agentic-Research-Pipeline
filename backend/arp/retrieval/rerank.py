"""Local cross-encoder reranking of retrieved chunks. First use downloads ~0.57 GB, and on a
4-core CPU scoring 40 chunks took ~47 s per field, so it is off by default until measured on
target hardware (Settings.rerank_enabled)."""

from __future__ import annotations

import logging

from arp import models
from arp.compute import client as compute_client
from arp.models import local
from arp.schemas.common import DocumentChunk

logger = logging.getLogger(__name__)

# Multilingual (EN/DE) cross-encoder, the smallest multilingual one fastembed
# lists (~0.57GB INT8 ONNX); the smaller ms-marco/jina-tiny models are English-only.
RERANK_MODEL_NAME = "BAAI/bge-reranker-v2-m3-int8"

_unavailable = False


def _get_model():
    return local.cross_encoder(RERANK_MODEL_NAME)


def _score(query: str, texts: list[str]) -> list[float]:
    return [float(s) for s in _get_model().rerank(query, texts)]


def rerank(query: str, chunks: list[DocumentChunk], top_n: int, scores_out: dict[str, float] | None = None) -> list[DocumentChunk]:
    """At most `top_n` of `chunks`, best cross-encoder score first. If the
    model can't load or score, returns `chunks[:top_n]` unchanged, warns once
    and skips every later call in this process (no per-field reload retries)
    -- reranking is a precision boost, never a hard dependency. `scores_out`, when given, receives
    each chunk's score, and stays empty when the model did not score."""
    global _unavailable
    if not chunks:
        return []
    if _unavailable:
        return chunks[:top_n]
    texts = [c.text for c in chunks]
    if compute_client.models_configured():  # the slow local model is never the fallback for the cloud one
        scores, _ = models.rerank(query, texts)
        if scores is None:
            return chunks[:top_n]
    else:
        try:
            scores, _ = models.rerank(query, texts, score=lambda q, ts: _score(q, ts))  # tests patch _score
        except Exception as exc:
            _unavailable = True
            logger.warning("Reranker unavailable (%s: %s); keeping retrieval order.", type(exc).__name__, exc)
            return chunks[:top_n]
    if scores_out is not None:
        scores_out.update({c.chunk_id: float(scores[i]) for i, c in enumerate(chunks)})
    order = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)  # stable on ties
    return [chunks[i] for i in order[:top_n]]
