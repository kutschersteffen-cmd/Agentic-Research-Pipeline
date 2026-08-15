from __future__ import annotations

import numpy as np

from arp.retrieval.index_cache import get_index_cache
from arp.schemas.common import DocType, DocumentChunk
from arp.storage.document_store import DocumentContentStore

_RRF_K = 60


def _rrf_fuse(rankings: list[list[str]], k: int = _RRF_K) -> list[str]:
    """Reciprocal rank fusion: each ranking contributes 1/(k + rank) to a
    chunk_id's score (0 if absent from that ranking -- not a penalty),
    summed across rankings, highest-score-first."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda cid: scores[cid], reverse=True)


def _vector_ranking(candidates: list[DocumentChunk], query_text: str, content_store: DocumentContentStore) -> list[str]:
    """Cosine-similarity ranking of `candidates` against `query_text`
    using local ONNX embeddings, cached in `content_store` per chunk_id
    (see DocumentContentStore.lookup_embeddings/store_embeddings) -- a
    chunk's embedding is a pure function of its text, so it's computed
    once and reused by every later run/field/activity that selects from
    it, not just within this one call."""
    from arp.retrieval.embeddings import EMBED_MODEL_NAME, embed_texts

    chunk_ids = [c.chunk_id for c in candidates]
    cached = content_store.lookup_embeddings(chunk_ids, EMBED_MODEL_NAME)
    missing = [c for c in candidates if c.chunk_id not in cached]
    if missing:
        vectors = embed_texts([c.text for c in missing])
        new_vectors = {c.chunk_id: vectors[i] for i, c in enumerate(missing)}
        content_store.store_embeddings(new_vectors, EMBED_MODEL_NAME)
        cached.update(new_vectors)

    query_vec = embed_texts([query_text])[0]
    query_norm = float(np.linalg.norm(query_vec)) or 1.0
    scored: list[tuple[str, float]] = []
    for c in candidates:
        vec = cached.get(c.chunk_id)
        if vec is None:
            continue
        vec_norm = float(np.linalg.norm(vec)) or 1.0
        similarity = float(np.dot(query_vec, vec)) / (query_norm * vec_norm)
        scored.append((c.chunk_id, similarity))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [chunk_id for chunk_id, _ in scored]


def select_relevant_chunks(
    chunks: list[DocumentChunk],
    query_terms: list[str],
    *,
    doc_type_filter: list[DocType] | None = None,
    max_chunks: int = 10,
    require_hit: bool = True,
    fallback_to_all: bool = False,
    hybrid_retrieval_enabled: bool = False,
    content_store: DocumentContentStore | None = None,
) -> list[DocumentChunk]:
    """BM25-ranked evidence selection applied before any extraction/
    matching LLM call, so a call's context stays small (higher precision,
    lower cost) instead of dumping an entire filing at it -- what makes
    per-field/per-activity evidence gathering affordable at a
    4000-company batch scale. Replaces what were four independent,
    duplicated keyword-hit-count selectors across the codebase with one
    shared implementation, backed by real BM25 relevance ranking instead
    of a raw hit-count sort -- still deterministic and embedding-free by
    default, so no added LLM/API cost versus what this app already paid
    for retrieval.

    - `doc_type_filter`: keep only chunks whose doc_type is in this list
      (None = no filter).
    - `query_terms`: empty means no ranking -- just doc_type_filter + a
      cap at `max_chunks`, in original order (matches call sites that pass
      no keywords at all, e.g. proxy-statement proposal extraction, where
      nothing to rank against exists).
    - `require_hit`: when query_terms is non-empty, drop chunks that
      scored 0 (no term overlap at all) before ranking/capping -- matches
      "only chunks that actually mention this" filtering used by most
      callers.
    - `fallback_to_all`: if `require_hit` filtering leaves nothing, fall
      back to the full (doc-type-filtered) candidate set instead of
      returning empty -- matches callers that would rather hand the LLM
      unranked evidence than none at all.
    - `hybrid_retrieval_enabled` / `content_store`: opt-in, both default
      to off/None, and every existing caller leaves them there -- so this
      is a strict addition, never a change to current behavior. When both
      are supplied, fuses BM25's ranking with a local-embedding cosine-
      similarity ranking via reciprocal rank fusion, so a company that
      describes a theme in vocabulary the seed keywords don't cover (e.g.
      "e-mobility transition" vs ["electrification"]) can still surface
      as evidence. `require_hit`'s zero-BM25-overlap filter still applies
      to BM25's contribution to the fusion, but not to the vector
      ranking -- catching exactly that vocabulary gap is the point.
      Grounding is unaffected either way: citations are still exact-
      matched against full_text regardless of which chunks were selected.
    """
    candidates = chunks
    if doc_type_filter:
        candidates = [c for c in candidates if c.doc_type in doc_type_filter]
    if not candidates:
        return []

    if not query_terms:
        return candidates[:max_chunks]

    cache = get_index_cache()
    key = cache.make_key(candidates)
    retriever, by_id = cache.get_or_build(key, candidates)
    query_text = " ".join(query_terms)
    results = retriever.retrieve(query_text)

    if require_hit:
        results = [r for r in results if (r.score or 0.0) > 0.0]

    use_hybrid = hybrid_retrieval_enabled and content_store is not None
    if not use_hybrid:
        if require_hit and not results and fallback_to_all:
            return candidates[:max_chunks]
        return [by_id[r.node.id_] for r in results[:max_chunks]]

    bm25_ranking = [r.node.id_ for r in results]
    vector_ranking = _vector_ranking(candidates, query_text, content_store)
    fused = _rrf_fuse([bm25_ranking, vector_ranking])
    if not fused and fallback_to_all:
        return candidates[:max_chunks]
    return [by_id[chunk_id] for chunk_id in fused[:max_chunks]]
