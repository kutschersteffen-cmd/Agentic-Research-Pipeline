from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

import numpy as np

from arp.storage import document_registry, embeddings_cache, parsed_content_cache
from arp.storage.document_registry import DocumentRegistry, StoredDocumentRef, derive_doc_id
from arp.storage.embeddings_cache import ChunkEmbeddingsCache
from arp.storage.parsed_content_cache import ParsedContent, ParsedContentCache

# Re-exported so every existing `from arp.storage.document_store import
# derive_doc_id / ParsedContent / StoredDocumentRef` call site (local_files.py,
# edgar.py, tests) keeps working unchanged even though these now live in
# their own collaborator modules.
__all__ = [
    "DocumentContentStore",
    "ParsedContent",
    "StoredDocumentRef",
    "derive_doc_id",
]

_DB_FILENAME = "content.db"

# One schema init call across all three collaborators' own fragments --
# see DocumentContentStore's docstring for why they share a single file.
_SCHEMA = parsed_content_cache.SCHEMA + "\n" + document_registry.SCHEMA + "\n" + embeddings_cache.SCHEMA


class DocumentContentStore:
    """Content-addressed cache of parsed document text, plus a
    company/doc_type -> doc_id directory for cross-run citation
    resolution, plus a chunk-embeddings cache for opt-in hybrid retrieval.

    A deliberate departure from every other store in this app: it uses
    stdlib sqlite3, the first database anywhere in this codebase, where
    every other store advertises "no database" and means it. That rule
    protects *user-authored* state (a run's manifest, an engagement's
    audit trail) that cannot be regenerated if lost or corrupted. This
    store holds only *derived* state -- deleting content.db costs nothing
    but re-parsing time.

    This class is a thin facade over three independent collaborators --
    ParsedContentCache, DocumentRegistry, ChunkEmbeddingsCache (see their
    own modules) -- that share one SQLite file and one connection recipe,
    not because their jobs are related, but because a single file gives
    one thing to back up/inspect/prune instead of three, and per-
    operation connect overhead (tens to low hundreds of microseconds) is
    negligible next to what any of the three actually do (a multi-second
    parse, a multi-MB row read, a batch embedding write). Each
    collaborator is independently readable and owns its own schema
    fragment; this facade only adds the parts that are genuinely
    cross-cutting -- schema init and the operator-facing stats() view.

    No lock() method anywhere in this store, deliberately: every write in
    every collaborator is an idempotent, content-addressed insert of a
    value that's a pure function of its key (INSERT ... ON CONFLICT DO
    NOTHING). There is no read-modify-write invariant to protect -- a lost
    write under concurrent writers costs one redundant recomputation, not
    a lost update, which is the whole distinction from the stores that do
    need KeyedLock. SQLite's own write transaction plus busy_timeout
    already serializes writers across processes, which a threading.RLock
    couldn't do anyway.

    Connections are opened per operation and always closed in `finally` --
    never shared across threads or held on an instance. That's what makes
    `check_same_thread` (sqlite3's default-True safety check) a non-issue
    without ever needing to pass check_same_thread=False: every connection
    is created, used, and closed on the one thread that opened it.

    WAL mode does not work over a network filesystem (NFS) -- keep
    store_dir local if you repoint it.
    """

    def __init__(self, store_dir: Path, enabled: bool = True) -> None:
        self.store_dir = store_dir
        self.enabled = enabled
        self._db_path = store_dir / _DB_FILENAME
        if self.enabled:
            self.store_dir.mkdir(parents=True, exist_ok=True)
            conn = self._connect()
            try:
                conn.executescript(_SCHEMA)
                conn.commit()
            finally:
                conn.close()

        self._parsed_content = ParsedContentCache(self._connect, enabled)
        self._registry = DocumentRegistry(self._connect, enabled)
        self._embeddings = ChunkEmbeddingsCache(self._connect, enabled)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5.0)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    # --- parsed-text cache (delegates to ParsedContentCache) ---------------

    def content_key_for_file(self, path: Path) -> str:
        return self._parsed_content.content_key_for_file(path)

    def lookup(self, content_key: str, parser_version: str) -> ParsedContent | None:
        return self._parsed_content.lookup(content_key, parser_version)

    def store(self, content_key: str, **kwargs) -> ParsedContent:
        return self._parsed_content.store(content_key, **kwargs)

    def get_or_compute(self, content_key: str, **kwargs) -> ParsedContent:
        return self._parsed_content.get_or_compute(content_key, **kwargs)

    def get_or_parse(self, path: Path, **kwargs) -> ParsedContent:
        return self._parsed_content.get_or_parse(path, **kwargs)

    def list_cached_content(self, offset: int, limit: int) -> tuple[list[dict], int]:
        return self._parsed_content.list_cached(offset, limit)

    def get_cached_text(self, row_id: int) -> ParsedContent | None:
        return self._parsed_content.get_full_text(row_id)

    # --- document directory (delegates to DocumentRegistry) ----------------

    def register_document(self, **kwargs) -> str:
        return self._registry.register_document(**kwargs)

    def resolve_document(self, doc_id: str) -> StoredDocumentRef | None:
        return self._registry.resolve_document(doc_id)

    def list_documents_by_content_keys(self, content_keys: list[str]) -> dict[str, StoredDocumentRef]:
        return self._registry.list_by_content_keys(content_keys)

    # --- chunk embeddings (delegates to ChunkEmbeddingsCache) ---------------

    def lookup_embeddings(self, chunk_ids: list[str], embed_model: str) -> dict[str, np.ndarray]:
        return self._embeddings.lookup_embeddings(chunk_ids, embed_model)

    def store_embeddings(self, vectors_by_chunk_id: dict[str, np.ndarray], embed_model: str) -> None:
        return self._embeddings.store_embeddings(vectors_by_chunk_id, embed_model)

    # --- operator surface (arp documents ... CLI) ---------------------------

    def stats(self) -> dict:
        """The one place this facade genuinely needs to know about all
        three collaborators -- presenting a unified operator view is this
        facade's actual job."""
        if not self.enabled:
            return {"enabled": False}
        conn = self._connect()
        try:
            merged = {"enabled": True}
            merged.update(self._parsed_content.stats(conn))
            merged.update(self._registry.stats(conn))
            merged.update(self._embeddings.stats(conn))
            merged["db_path"] = str(self._db_path)
            return merged
        finally:
            conn.close()

    def prune(self, *, keep_parser_version: str | Iterable[str]) -> int:
        """Only parsed_content accumulates parser-version-orphaned rows;
        the document registry and embeddings cache have no equivalent
        concept, so this delegates entirely."""
        return self._parsed_content.prune(keep_parser_version=keep_parser_version)
