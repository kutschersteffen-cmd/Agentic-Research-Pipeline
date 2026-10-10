from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

import numpy as np

from arp.db.documents import DocumentRegistry, StoredDocumentRef, derive_doc_id
from arp.storage import parsed_content_cache
from arp.storage.parsed_content_cache import ParsedContent, ParsedContentCache
from arp.storage.postgres_embeddings import PgVectorEmbeddingsStore
from arp.storage.safe_path import UnsafeIdentifierError, safe_id

# Re-exported so every existing `from arp.storage.document_store import
# derive_doc_id / ParsedContent / StoredDocumentRef` call site (local_files.py,
# edgar.py, tests) keeps working unchanged even though these now live in
# their own collaborator modules.
__all__ = [
    "DocumentContentStore",
    "ParsedContent",
    "StoredDocumentRef",
    "derive_doc_id",
    "files_on_disk",
]

_DB_FILENAME = "content.db"


def files_on_disk(documents_dir: Path, company_id: str) -> int:
    try:
        company_dir = documents_dir / safe_id(company_id, label="company_id")
    except UnsafeIdentifierError:
        return 0
    return sum(1 for f in company_dir.rglob("*") if f.is_file()) if company_dir.is_dir() else 0


class DocumentContentStore:
    """Content-addressed cache of parsed document text (SQLite content.db, derived data -- deleting it
    costs only re-parsing time), plus the Postgres document registry (company/doc_type -> doc_id, for
    cross-run citation resolution) and the pgvector chunk-embeddings store for hybrid retrieval.

    A thin facade over three collaborators -- ParsedContentCache (SQLite), DocumentRegistry and
    PgVectorEmbeddingsStore (Postgres) -- adding only the cross-cutting parts: schema init and the
    operator-facing stats() view.

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

    def __init__(self, store_dir: Path, enabled: bool = True, *, dsn: str) -> None:
        self.store_dir = store_dir
        self.enabled = enabled
        self._db_path = store_dir / _DB_FILENAME
        if self.enabled:
            self.store_dir.mkdir(parents=True, exist_ok=True)
            conn = self._connect()
            try:
                conn.executescript(parsed_content_cache.SCHEMA)
                conn.commit()
                parsed_content_cache.ensure_columns(conn)
            finally:
                conn.close()

        self._parsed_content = ParsedContentCache(self._connect, enabled)
        self._registry = DocumentRegistry(dsn, enabled)
        self._embeddings = PgVectorEmbeddingsStore(dsn)

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

    def set_storage_uri(self, doc_id: str, storage_uri: str) -> None:
        return self._registry.set_storage_uri(doc_id, storage_uri)

    def set_identity(self, doc_id: str, **kwargs) -> None:
        return self._registry.set_identity(doc_id, **kwargs)

    def list_family(self, family_id: str) -> list[StoredDocumentRef]:
        return self._registry.list_family(family_id)

    def list_all_documents(self) -> list[StoredDocumentRef]:
        return self._registry.list_all()

    def readiness_by_company(self, company_ids: list[str]) -> dict[str, dict]:
        return self._registry.readiness_by_company(company_ids, self._parsed_content.parsed_keys)

    # --- chunk embeddings (delegates to PgVectorEmbeddingsStore) ---------------

    def lookup_embeddings(self, chunk_ids: list[str], embed_model: str) -> dict[str, np.ndarray]:
        return self._embeddings.lookup_embeddings(chunk_ids, embed_model) if self.enabled else {}

    def store_embeddings(self, vectors_by_chunk_id: dict[str, np.ndarray], embed_model: str) -> None:
        if self.enabled:
            self._embeddings.store_embeddings(vectors_by_chunk_id, embed_model)

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
            merged.update(self._registry.stats())
            merged["db_path"] = str(self._db_path)
            return merged
        finally:
            conn.close()

    def prune(self, *, keep_parser_version: str | Iterable[str]) -> int:
        """Only parsed_content accumulates parser-version-orphaned rows;
        the document registry and embeddings cache have no equivalent
        concept, so this delegates entirely."""
        return self._parsed_content.prune(keep_parser_version=keep_parser_version)
