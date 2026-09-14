from __future__ import annotations

import hashlib
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from arp.schemas.common import new_id, now_iso
from arp.storage.safe_path import safe_id

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id         TEXT PRIMARY KEY,
    company_id     TEXT NOT NULL,
    doc_type       TEXT NOT NULL,
    content_key    TEXT NOT NULL,
    title          TEXT NOT NULL,
    local_path     TEXT,
    source_url     TEXT,
    storage_uri    TEXT,
    first_seen_at  TEXT NOT NULL,
    last_seen_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_documents_company ON documents (company_id, doc_type);
CREATE INDEX IF NOT EXISTS ix_documents_content ON documents (content_key);
"""


def ensure_storage_uri_column(conn: sqlite3.Connection) -> None:
    """Additive migration for databases created before storage_uri existed
    -- `CREATE TABLE IF NOT EXISTS` in SCHEMA above only covers a fresh
    database, so an existing `documents` table needs this explicit
    ALTER TABLE instead. Idempotent: a no-op once the column exists."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(documents)").fetchall()}
    if "storage_uri" not in cols:
        conn.execute("ALTER TABLE documents ADD COLUMN storage_uri TEXT")
        conn.commit()


@dataclass(frozen=True, slots=True)
class StoredDocumentRef:
    doc_id: str
    company_id: str
    doc_type: str
    content_key: str
    title: str
    local_path: str | None
    source_url: str | None
    storage_uri: str | None = None


def derive_doc_id(company_id: str, doc_type: str, content_key: str) -> str:
    """A document's identity is (company, doc_type, bytes) -- what a "view
    source" link means -- so its id is a deterministic hash of exactly
    those three things, not a random one minted per parse. Deliberately
    excludes parser_version: the parse is an implementation detail, and a
    citation should keep resolving to the same document across a parser
    upgrade even though re-grounding it may then produce a different
    page/grounded result.

    16 hex chars (64 bits), not new_id()'s 12 (48 bits): at 48 bits, ~120k
    derived ids already carry a ~2.5e-5 birthday-collision chance, and a
    collision here means grounding checks a citation against the wrong
    document's text. 64 bits puts that at ~4e-10. See
    DocumentRegistry.register_document for the collision guard this is
    paired with.
    """
    safe_id(company_id, label="company_id")
    payload = f"{company_id}\x00{doc_type}\x00{content_key}"
    return f"doc_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


class DocumentRegistry:
    """doc_id -> (company_id, doc_type, content_key) directory (the
    documents table), for cross-run citation resolution -- distinct from
    ParsedContentCache's job of caching the parsed text itself. One of
    DocumentContentStore's three collaborators (see
    arp/storage/document_store.py).
    """

    def __init__(self, connect: Callable[[], sqlite3.Connection], enabled: bool) -> None:
        self._connect = connect
        self.enabled = enabled

    def register_document(
        self,
        *,
        doc_id: str,
        company_id: str,
        doc_type: str,
        content_key: str,
        title: str,
        local_path: str | None,
        source_url: str | None,
    ) -> str:
        """Records doc_id -> (company_id, doc_type, content_key) so a
        citation persisted in one run resolves to the same document on a
        later run. Returns the doc_id actually stored under: normally the
        same one passed in, but if an existing row for that doc_id already
        maps to a *different* (company_id, content_key) -- a collision,
        astronomically unlikely at 64 bits but checked rather than
        assumed away -- logs an error and falls back to a fresh random id
        for this document rather than silently overwriting the existing
        mapping (which would point some other document's past citations
        at the wrong text)."""
        if not self.enabled:
            return doc_id
        safe_id(company_id, label="company_id")
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT company_id, content_key FROM documents WHERE doc_id=?", (doc_id,)
            ).fetchone()
            if existing is not None and (existing[0], existing[1]) != (company_id, content_key):
                logger.error(
                    "doc_id collision: %s already maps to company_id=%s content_key=%s; assigning a fresh id for "
                    "company_id=%s content_key=%s instead",
                    doc_id,
                    existing[0],
                    existing[1],
                    company_id,
                    content_key,
                )
                doc_id = new_id("doc")

            now = now_iso()
            conn.execute(
                "INSERT INTO documents (doc_id, company_id, doc_type, content_key, title, local_path, source_url, "
                " first_seen_at, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(doc_id) DO UPDATE SET "
                " last_seen_at=excluded.last_seen_at, local_path=excluded.local_path, "
                " title=excluded.title, content_key=excluded.content_key",
                (doc_id, company_id, doc_type, content_key, title, local_path, source_url, now, now),
            )
            conn.commit()
            return doc_id
        finally:
            conn.close()

    def resolve_document(self, doc_id: str) -> StoredDocumentRef | None:
        if not self.enabled:
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT doc_id, company_id, doc_type, content_key, title, local_path, source_url, storage_uri "
                "FROM documents WHERE doc_id=?",
                (doc_id,),
            ).fetchone()
            if row is None:
                return None
            return StoredDocumentRef(*row)
        finally:
            conn.close()

    def set_storage_uri(self, doc_id: str, storage_uri: str) -> None:
        """Records where a document's immutable original bytes ended up in
        object storage (see arp/storage/document_blob_store.py), after the
        fact -- registration itself never blocks on an object-store upload,
        so this is a separate, best-effort follow-up call."""
        if not self.enabled:
            return
        conn = self._connect()
        try:
            conn.execute("UPDATE documents SET storage_uri=? WHERE doc_id=?", (storage_uri, doc_id))
            conn.commit()
        finally:
            conn.close()

    def list_by_content_keys(self, content_keys: list[str]) -> dict[str, StoredDocumentRef]:
        """Batch lookup for enriching a page of parsed_content rows with
        company_id/doc_type/title/local_path in one query instead of N --
        used by the "view stored extractions" browser, which only has each
        row's content_key (parsed_content has no company/doc_type identity
        of its own). Content-addressed, so in the rare case more than one
        document shares a content_key (identical bytes registered under
        different company/doc_type), the last row read wins -- acceptable
        for a display-only enrichment, unlike register_document's identity
        guarantees."""
        if not self.enabled or not content_keys:
            return {}
        conn = self._connect()
        try:
            placeholders = ",".join("?" for _ in content_keys)
            rows = conn.execute(
                f"SELECT doc_id, company_id, doc_type, content_key, title, local_path, source_url, storage_uri "
                f"FROM documents WHERE content_key IN ({placeholders})",
                content_keys,
            ).fetchall()
            return {row[3]: StoredDocumentRef(*row) for row in rows}
        finally:
            conn.close()

    def list_all(self) -> list[StoredDocumentRef]:
        """Every registered document, for backfill/reindex use (`arp db
        reindex documents`/`opensearch`/`object-store`) -- not used on any
        hot path, so no pagination is offered."""
        if not self.enabled:
            return []
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT doc_id, company_id, doc_type, content_key, title, local_path, source_url, storage_uri "
                "FROM documents ORDER BY doc_id"
            ).fetchall()
            return [StoredDocumentRef(*row) for row in rows]
        finally:
            conn.close()

    def stats(self, conn: sqlite3.Connection) -> dict:
        """Takes an already-open connection -- called by
        DocumentContentStore.stats() as part of one cross-cutting operator
        view alongside the other collaborators' counts."""
        doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        return {"registered_documents": doc_count}
