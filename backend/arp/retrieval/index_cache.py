from __future__ import annotations

import threading
from collections import OrderedDict

from llama_index.core.schema import TextNode
from llama_index.retrievers.bm25 import BM25Retriever

from arp.schemas.common import DocumentChunk

# BM25Retriever.from_defaults measured at ~40ms on a realistic ~500-chunk
# corpus -- well over the ~20ms gate this cache's existence was
# conditioned on. A multi-field extraction schema calls
# select_relevant_chunks once per field over the same document set, so
# this eliminates most of that cost.
_MAX_CACHED_INDEXES = 16


class BM25IndexCache:
    """Caches a built BM25Retriever (plus its chunk_id -> DocumentChunk
    lookup) per distinct candidate set, so a multi-field/multi-activity
    caller that re-selects evidence from the same document corpus doesn't
    rebuild the index every time.

    Keyed on the ordered tuple of candidate chunk_ids -- distinct filter
    combinations (a different doc_type_filter) naturally produce a
    different key, so this only reuses an index when the corpus being
    indexed is exactly the same. Filtering happens on the *candidate set
    before* it reaches this cache, never on retrieved results after
    (BM25 scores depend on corpus statistics like IDF/avgdl, so indexing
    the unfiltered corpus and filtering results afterward would silently
    change ranking and scores) -- select_evidence.py preserves that order.

    Same pattern as arp.ingestion.chunk_spans.ChunkSpanCache: a plain
    dict-guarding lock, never held across the (expensive) build itself.
    A lost race just costs one redundant build, not a correctness issue,
    since the built retriever is a pure function of its key.
    """

    def __init__(self, max_entries: int = _MAX_CACHED_INDEXES) -> None:
        self._max_entries = max_entries
        self._entries: OrderedDict[tuple[str, ...], tuple[BM25Retriever, dict[str, DocumentChunk]]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def make_key(candidates: list[DocumentChunk]) -> tuple[str, ...]:
        return tuple(c.chunk_id for c in candidates)

    def get_or_build(
        self, key: tuple[str, ...], candidates: list[DocumentChunk]
    ) -> tuple[BM25Retriever, dict[str, DocumentChunk]]:
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)
                return cached

        nodes = [TextNode(id_=c.chunk_id, text=c.text) for c in candidates]
        by_id = {c.chunk_id: c for c in candidates}
        retriever = BM25Retriever.from_defaults(nodes=nodes, similarity_top_k=len(nodes))
        entry = (retriever, by_id)

        with self._lock:
            self._entries[key] = entry
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
        return entry

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def stats(self) -> dict:
        with self._lock:
            return {"entries": len(self._entries)}


_INDEX_CACHE = BM25IndexCache()


def get_index_cache() -> BM25IndexCache:
    return _INDEX_CACHE


def clear_index_cache() -> None:
    _INDEX_CACHE.clear()
