from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Callable

import numpy as np

from arp.compute import client as compute_client
from arp.models.registry import entry, model_header
from arp.retrieval.index_cache import INDEX_CACHE
from arp.retrieval.rerank import RERANK_KEYS, rerank
from arp.schemas.common import DocType, DocumentChunk
from arp.storage.document_store import DocumentContentStore

_RRF_K = 60
# Concurrent fields (worker threads) share a document's chunks: one embeds the missing ones, the rest reuse them.
_EMBED_LOCK = threading.Lock()
_FALLBACK_WARNING = "arp-models unavailable; embedding with MiniLM"

logger = logging.getLogger(__name__)


def _rrf_fuse(rankings: list[list[str]], k: int = _RRF_K, scores_out: dict[str, float] | None = None) -> list[str]:
    """Reciprocal rank fusion: each ranking contributes 1/(k + rank) to a
    chunk_id's score (0 if absent from that ranking -- not a penalty),
    summed across rankings, highest-score-first."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    if scores_out is not None:
        scores_out.update(scores)
    return sorted(scores, key=lambda cid: scores[cid], reverse=True)


def _opensearch_bm25_ranking(candidates: list[DocumentChunk], query_text: str, client) -> list[tuple[str, float]]:
    """BM25 ranking computed by OpenSearch's arp-chunks index instead of
    the in-memory LlamaIndex retriever -- a `terms` filter on the
    candidates' chunk_ids keeps ranking scoped to exactly this call's
    candidate set (matching BM25IndexCache's own "index only the filtered
    corpus, never filter results afterward" invariant, since OpenSearch's
    BM25 statistics would otherwise reflect the whole corpus, not just
    these candidates), plus a `multi_match` on `text`. Returns
    (chunk_id, score) pairs, highest first -- chunk_ids not present in
    OpenSearch (e.g. not yet indexed) are simply absent, not an error."""
    chunk_ids = [c.chunk_id for c in candidates]
    body = {
        "query": {
            "bool": {
                "filter": {"terms": {"chunk_id": chunk_ids}},
                "must": {"multi_match": {"query": query_text, "fields": ["text"]}},
            }
        },
        "size": len(chunk_ids),
    }
    response = client.search(index="arp-chunks", body=body)
    return [(hit["_source"]["chunk_id"], hit["_score"]) for hit in response["hits"]["hits"]]


def _embedding_key(chunk: DocumentChunk, text: str) -> str:
    """Cache key of a chunk's vector. The chunk's own text is fixed by its id (doc + offsets), so the id alone
    keys it, as before; any other index text (context headers) adds a hash of the exact text embedded, so
    the two never share a vector."""
    if text == chunk.text:
        return chunk.chunk_id
    return f"{chunk.chunk_id}#{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"


def _vector_ranking(
    candidates: list[DocumentChunk], query_text: str, content_store: DocumentContentStore,
    texts: dict[str, str] | None = None,
) -> list[str]:
    """Cosine-similarity ranking of `candidates` against `query_text`
    using local ONNX embeddings, cached in `content_store` per chunk_id (+ text hash for index text)
    (see DocumentContentStore.lookup_embeddings/store_embeddings) -- a
    chunk's embedding is a pure function of its text, so it's computed
    once and reused by every later run/field/activity that selects from
    it, not just within this one call."""
    from arp.retrieval.embeddings import EMBED_MODEL_NAME, embed_texts

    texts = texts or {c.chunk_id: c.text for c in candidates}
    keys = {c.chunk_id: _embedding_key(c, texts[c.chunk_id]) for c in candidates}
    cached = content_store.lookup_embeddings(list(keys.values()), EMBED_MODEL_NAME)
    if any(k not in cached for k in keys.values()):
        with _EMBED_LOCK:
            cached = content_store.lookup_embeddings(list(keys.values()), EMBED_MODEL_NAME)  # another field may have stored them
            missing = [c for c in candidates if keys[c.chunk_id] not in cached]
            if missing:
                vectors = embed_texts([texts[c.chunk_id] for c in missing])
                new_vectors = {keys[c.chunk_id]: vectors[i] for i, c in enumerate(missing)}
                content_store.store_embeddings(new_vectors, EMBED_MODEL_NAME)
                cached.update(new_vectors)

    return _cosine_ranking(candidates, keys, cached, embed_texts([query_text])[0])


def _cosine_ranking(
    candidates: list[DocumentChunk], keys: dict[str, str], cached: dict[str, np.ndarray], query_vec: np.ndarray
) -> list[str]:
    query_norm = float(np.linalg.norm(query_vec)) or 1.0
    scored: list[tuple[str, float]] = []
    for c in candidates:
        vec = cached.get(keys[c.chunk_id])
        if vec is None:
            continue
        vec_norm = float(np.linalg.norm(vec)) or 1.0
        similarity = float(np.dot(query_vec, vec)) / (query_norm * vec_norm)
        scored.append((c.chunk_id, similarity))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [chunk_id for chunk_id, _ in scored]


def _model_vector_ranking(
    candidates: list[DocumentChunk], query_text: str, content_store: DocumentContentStore,
    texts: dict[str, str], key: str,
) -> list[str] | None:
    """_vector_ranking with registry embed model `key` on arp-models: vectors cached under the same keys as
    MiniLM's, with the model's hf_id. None when arp-models is not configured or any call fails or answers
    vectors of the wrong size, so the caller ranks the whole field with MiniLM; vectors that did come back
    stay stored."""
    from arp.retrieval.embeddings import PREFIXES

    if not compute_client.models_configured():
        return None
    e = entry(key)
    query_prefix, passage_prefix = PREFIXES.get(key, ("", ""))

    def remote(batch: list[str]) -> np.ndarray | None:
        try:
            vectors = compute_client.embed(batch, model_header(e), e.dim)
        except Exception as exc:  # noqa: BLE001 - an outage costs the better model, never the run
            logger.warning("arp-models embed failed (%s: %s).", type(exc).__name__, exc)
            return None
        vectors = None if vectors is None else np.asarray(vectors, dtype=np.float32)
        return vectors if vectors is not None and vectors.shape == (len(batch), e.dim) else None

    keys = {c.chunk_id: _embedding_key(c, texts[c.chunk_id]) for c in candidates}
    cached = content_store.lookup_embeddings(list(keys.values()), e.hf_id)
    if any(k not in cached for k in keys.values()):
        with _EMBED_LOCK:
            cached = content_store.lookup_embeddings(list(keys.values()), e.hf_id)
            missing = [c for c in candidates if keys[c.chunk_id] not in cached]
            if missing:
                vectors = remote([passage_prefix + texts[c.chunk_id] for c in missing])
                if vectors is None:
                    return None
                new_vectors = {keys[c.chunk_id]: vectors[i] for i, c in enumerate(missing)}
                content_store.store_embeddings(new_vectors, e.hf_id)
                cached.update(new_vectors)
    query_vec = remote([query_prefix + query_text])
    return None if query_vec is None else _cosine_ranking(candidates, keys, cached, query_vec[0])


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
    retrieval_backend: str = "bm25",
    opensearch_client=None,
    rerank_candidates: int | None = None,
    on_unranked_fallback: Callable[[], None] | None = None,
    index_texts: dict[str, str] | None = None,
    explain: dict | None = None,
    parents: dict[str, DocumentChunk] | None = None,
    embed_model: str = "minilm",
    rerank_model: str = "cross-encoder",
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
    - `retrieval_backend` / `opensearch_client`: opt-in, default to
      "bm25"/None, and every existing caller leaves them there -- so this
      is a strict addition, never a change to current behavior. When
      `retrieval_backend == "opensearch"` and `opensearch_client` is
      supplied, the BM25 half is computed by OpenSearch's arp-chunks
      index (see `_opensearch_bm25_ranking`) instead of the in-memory
      LlamaIndex retriever -- everything downstream (`require_hit`,
      `fallback_to_all`, RRF fusion with `hybrid_retrieval_enabled`'s
      local-embedding ranking) is unchanged, since this only swaps who
      computes the BM25 half, not what happens to its output.
    - `rerank_candidates`: when set, the top `rerank_candidates` of the final
      ranking (fused, BM25, or the `fallback_to_all` candidates) are reordered
      by the local cross-encoder (see arp/retrieval/rerank.py) and the best
      `max_chunks` kept. None (default) leaves the ranking untouched.
    - `on_unranked_fallback`: called when `fallback_to_all` returns candidates
      that nothing ranked (no keyword hit, no vector ranking, no reranker), i.e.
      the first chunks in document order.
    - `index_texts`: chunk_id -> the text BM25 and the embedding ranking index (see
      arp/retrieval/index_text.py); a chunk not in it is indexed by its own text. Never changes the
      chunks returned, only their ranking.
    - `explain`: when given, filled with why these chunks were picked (the Argus
      Walkthrough shows it): `method`, `reranked`, `candidates`, per-chunk `scores`
      (`bm25`, `vector_rank`, `rrf`, `rerank`, each only when computed) for the
      returned chunks and `near_misses`, the up to 3 chunk ids ranked right after
      the cut. The return value is the same with or without it.
    - `parents`: small-to-big (candidate id -> the chunk returned in its place). Each ranking becomes a
      ranking of parents before fusion: a parent takes its best candidate's rank (and BM25 score), its other
      candidates drop out. Scores, near-misses and the reranker then see parents.
    - `embed_model` / `rerank_model`: Settings.embed_model / rerank_model. A model other than minilm that
      can't run (no arp-models, or a failed call) ranks the field with MiniLM; colbert that can't run keeps
      the order. `explain` gets `embed_model` and `rerank_model`: the registry key that ranked, else None.
    """
    scores: dict[str, dict] = {}
    ran: dict[str, str | None] = {"embed_model": None, "rerank_model": None}
    candidates = chunks
    if doc_type_filter:
        candidates = [c for c in candidates if c.doc_type in doc_type_filter]
    if not candidates:
        return []

    def record(method: str, picked: list[DocumentChunk], rest: list[DocumentChunk], reranked: bool = False) -> list[DocumentChunk]:
        if explain is not None:
            near = [c.chunk_id for c in rest[:3]]
            keep = [c.chunk_id for c in picked] + near
            explain.update(
                method=method, reranked=reranked, candidates=len(candidates),
                scores={cid: scores[cid] for cid in keep if scores.get(cid)}, near_misses=near, **ran,
            )
        return picked

    if not query_terms:
        return record("none", candidates[:max_chunks], [])

    query_text = " ".join(query_terms)
    texts = {c.chunk_id: (index_texts or {}).get(c.chunk_id, c.text) for c in candidates}

    def finish(ranked: list[DocumentChunk], method: str) -> list[DocumentChunk]:
        if rerank_candidates is None:
            return record(method, ranked[:max_chunks], ranked[max_chunks:])
        pool = ranked[:rerank_candidates]
        rerank_scores: dict[str, float] | None = {} if explain is not None else None
        picked = rerank(query_text, pool, max_chunks, scores_out=rerank_scores, model=rerank_model)
        if not rerank_scores:  # not recording, or the model did not score
            return record(method, picked, pool[max_chunks:])
        ran["rerank_model"] = RERANK_KEYS[rerank_model]
        for cid, score in rerank_scores.items():
            scores.setdefault(cid, {})["rerank"] = score
        chosen = {c.chunk_id for c in picked}
        rest = sorted((c for c in pool if c.chunk_id not in chosen), key=lambda c: rerank_scores[c.chunk_id], reverse=True)
        return record(method, picked, rest, reranked=True)

    use_opensearch_bm25 = retrieval_backend == "opensearch" and opensearch_client is not None
    if use_opensearch_bm25:
        by_id = {c.chunk_id: c for c in candidates}
        scored = _opensearch_bm25_ranking(candidates, query_text, opensearch_client)
    else:
        key = INDEX_CACHE.make_key(candidates, texts)
        retriever, by_id = INDEX_CACHE.get_or_build(key, candidates, texts)
        results = retriever.retrieve(query_text)
        scored = [(r.node.id_, r.score or 0.0) for r in results]

    if require_hit:
        scored = [(chunk_id, score) for chunk_id, score in scored if score > 0.0]
    if parents:
        best: dict[str, float] = {}
        for chunk_id, score in scored:  # highest first, so the first piece seen is the parent's best
            best.setdefault(parents[chunk_id].chunk_id, score)
        scored = list(best.items())
        by_id = {p.chunk_id: p for p in parents.values()}
    for chunk_id, score in scored:
        scores.setdefault(chunk_id, {})["bm25"] = float(score)
    bm25_method = "opensearch" if use_opensearch_bm25 else "bm25"

    use_hybrid = hybrid_retrieval_enabled and content_store is not None
    if not use_hybrid:
        if require_hit and not scored and fallback_to_all:
            if on_unranked_fallback is not None and rerank_candidates is None:
                on_unranked_fallback()
            return finish(candidates, "unranked")
        return finish([by_id[chunk_id] for chunk_id, _ in scored], bm25_method)

    bm25_ranking = [chunk_id for chunk_id, _ in scored]
    from arp.retrieval.embeddings import EMBED_KEYS

    embed_key = EMBED_KEYS[embed_model]
    vector_ranking = (
        _model_vector_ranking(candidates, query_text, content_store, texts, embed_key) if embed_key != "embed" else None
    )
    if vector_ranking is None:
        if embed_key != "embed" and _FALLBACK_WARNING not in compute_client._warned:  # once per process
            compute_client._warned.add(_FALLBACK_WARNING)
            logger.warning(_FALLBACK_WARNING)
        embed_key = "embed"
        vector_ranking = (
            _vector_ranking(candidates, query_text, content_store, texts=texts) if index_texts
            else _vector_ranking(candidates, query_text, content_store)
        )
    ran["embed_model"] = embed_key
    if parents:
        vector_ranking = list(dict.fromkeys(parents[chunk_id].chunk_id for chunk_id in vector_ranking))
    rrf: dict[str, float] = {}
    fused = _rrf_fuse([bm25_ranking, vector_ranking], scores_out=rrf)
    for rank, chunk_id in enumerate(vector_ranking, start=1):
        scores.setdefault(chunk_id, {})["vector_rank"] = rank
    for chunk_id, score in rrf.items():
        scores.setdefault(chunk_id, {})["rrf"] = score
    if not fused and fallback_to_all:
        return finish(candidates, "unranked")
    return finish([by_id[chunk_id] for chunk_id in fused], "hybrid" if bm25_method == "bm25" else "opensearch_hybrid")
