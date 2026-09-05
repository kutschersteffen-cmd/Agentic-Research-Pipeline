from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from arp.schemas.common import DocType

# Bumped whenever the split/section/speaker-detection logic changes, so a
# changed algorithm never returns a stale span computed under the old one
# -- the same "a changed input orphans old entries" idiom as
# arp/llm/cache.py::DiskLLMCache.make_key, just for an in-process cache.
_SPAN_ALGO_VERSION = 1

_MAX_CACHED_DOCUMENTS = 256


@dataclass(frozen=True, slots=True)
class ChunkSpan:
    """Everything about a chunk that's independent of which keywords a
    caller asked for -- the ~90% of chunk_document's cost (splitting,
    section/speaker detection) that's identical across every field/
    activity that chunks the same document."""

    char_start: int
    char_end: int
    section: str | None
    speaker: str | None


class ChunkSpanCache:
    """Bounded, process-global cache of a document's chunk spans.

    Deliberately caches spans (~40 bytes each), never full DocumentChunk
    objects: a DocumentChunk carries its own chunk text, so a cached list
    of them would make the ~1.09x (chunk overlap) text duplication
    permanent for the cache's lifetime -- for a 300-page PDF that's ~1.7MB
    per cache slot instead of ~20KB. Re-slicing text and recomputing
    keyword_hits from a span is cheap; re-running LlamaIndex's
    SentenceSplitter is not.

    Keyed on (algorithm version, doc_type, len(text), hash(text),
    chunk_chars, overlap_chars) -- not on doc_id, so two SourceDocuments
    with identical text share one entry. Uses the builtin hash() rather
    than a cryptographic hash: CPython memoizes a str's hash after first
    computation, so this is O(n) once per distinct string and O(1) for
    every redundant call against the same object, unlike sha256 which
    would redo a full pass every time. This key must never be persisted
    (str hashing is randomized per process).

    Thread-safe for concurrent readers/writers (the batch runner's workers
    and FastAPI's sync-route threadpool can both call chunk_document
    concurrently): a plain lock guards only the dict's get/put, never held
    across the actual computation. A cache miss racing another miss for
    the same key just means both callers compute once and the second
    write wins -- the value is a pure function of the key, so a lost write
    costs one recomputation, not a correctness problem. This is why there
    is no KeyedLock here: KeyedLock exists to protect a read-modify-write
    invariant, and there isn't one.
    """

    def __init__(self, max_entries: int = _MAX_CACHED_DOCUMENTS) -> None:
        self._max_entries = max_entries
        self._entries: OrderedDict[tuple, tuple[ChunkSpan, ...]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def make_key(text: str, doc_type: DocType, chunk_chars: int, overlap_chars: int) -> tuple:
        return (_SPAN_ALGO_VERSION, doc_type.value, len(text), hash(text), chunk_chars, overlap_chars)

    def get_or_compute(self, key: tuple, compute: Callable[[], tuple[ChunkSpan, ...]]) -> tuple[ChunkSpan, ...]:
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)
                return cached

        spans = compute()

        with self._lock:
            self._entries[key] = spans
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
        return spans

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def stats(self) -> dict:
        with self._lock:
            return {"entries": len(self._entries), "max_entries": self._max_entries}


# Process-global and bounded: the redundancy this cache eliminates is
# within one company's work (field x doc, activity x doc), but chunk_document
# is called from seven call sites nested inside LangGraph node functions --
# threading a cache handle down through every graph state would touch all
# of them for no change in hit rate. A bounded global gets the same result
# with zero call-site churn, and evicts as the batch's working set rolls
# forward instead of accumulating over a 4000-company run.
_SPAN_CACHE = ChunkSpanCache()


def get_span_cache() -> ChunkSpanCache:
    return _SPAN_CACHE


def clear_span_cache() -> None:
    """Test/debug escape hatch -- production code never needs this."""
    _SPAN_CACHE.clear()


def span_cache_stats() -> dict:
    return _SPAN_CACHE.stats()
