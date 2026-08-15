from __future__ import annotations

from arp.retrieval.index_cache import get_index_cache
from arp.schemas.common import DocType, DocumentChunk


def select_relevant_chunks(
    chunks: list[DocumentChunk],
    query_terms: list[str],
    *,
    doc_type_filter: list[DocType] | None = None,
    max_chunks: int = 10,
    require_hit: bool = True,
    fallback_to_all: bool = False,
) -> list[DocumentChunk]:
    """BM25-ranked evidence selection applied before any extraction/
    matching LLM call, so a call's context stays small (higher precision,
    lower cost) instead of dumping an entire filing at it -- what makes
    per-field/per-activity evidence gathering affordable at a
    4000-company batch scale. Replaces what were four independent,
    duplicated keyword-hit-count selectors across the codebase with one
    shared implementation, backed by real BM25 relevance ranking instead
    of a raw hit-count sort -- still deterministic and embedding-free, so
    no added LLM/API cost versus what this app already paid for retrieval.

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
    results = retriever.retrieve(" ".join(query_terms))

    if require_hit:
        results = [r for r in results if (r.score or 0.0) > 0.0]
        if not results and fallback_to_all:
            return candidates[:max_chunks]

    return [by_id[r.node.id_] for r in results[:max_chunks]]
