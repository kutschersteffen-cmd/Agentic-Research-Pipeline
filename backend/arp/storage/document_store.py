from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from arp.schemas.common import new_id, now_iso
from arp.storage.safe_path import safe_id

logger = logging.getLogger(__name__)

_DB_FILENAME = "content.db"

# A row's payload is never UPDATEd, only inserted once per
# (content_key, parser_version); a parser upgrade orphans old rows rather
# than touching them (see arp/ingestion/local_files.py::parser_version).
# Deliberately a normal rowid table, not WITHOUT ROWID -- full_text can be
# several MB, and forcing that into the PK's own B-tree (what WITHOUT
# ROWID does) causes overflow-page churn a separate rowid table avoids.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS parsed_content (
    id              INTEGER PRIMARY KEY,
    content_key     TEXT    NOT NULL,
    key_kind        TEXT    NOT NULL,
    parser_version  TEXT    NOT NULL,
    source_suffix   TEXT    NOT NULL,
    full_text       TEXT    NOT NULL,
    page_breaks     TEXT    NOT NULL DEFAULT '[]',
    text_sha256     TEXT    NOT NULL,
    char_len        INTEGER NOT NULL,
    byte_size       INTEGER NOT NULL,
    created_at      TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_parsed_content_key
    ON parsed_content (content_key, parser_version);

CREATE TABLE IF NOT EXISTS file_identity (
    abs_path     TEXT    PRIMARY KEY,
    size_bytes   INTEGER NOT NULL,
    mtime_ns     INTEGER NOT NULL,
    content_key  TEXT    NOT NULL,
    seen_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id         TEXT PRIMARY KEY,
    company_id     TEXT NOT NULL,
    doc_type       TEXT NOT NULL,
    content_key    TEXT NOT NULL,
    title          TEXT NOT NULL,
    local_path     TEXT,
    source_url     TEXT,
    first_seen_at  TEXT NOT NULL,
    last_seen_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_documents_company ON documents (company_id, doc_type);
CREATE INDEX IF NOT EXISTS ix_documents_content ON documents (content_key);
"""

# Mirrors arp/research/taxonomy_sources/fetch.py::_MAX_ORIGINAL_BYTES --
# don't persist anything absurdly large. A miss on an oversized document
# just means it's parsed fresh every time instead of cached; not an error.
_MAX_CACHED_CHARS = 32_000_000


@dataclass(frozen=True, slots=True)
class ParsedContent:
    content_key: str
    full_text: str
    page_breaks: list[int]
    text_sha256: str


@dataclass(frozen=True, slots=True)
class StoredDocumentRef:
    doc_id: str
    company_id: str
    doc_type: str
    content_key: str
    title: str
    local_path: str | None
    source_url: str | None


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
    DocumentContentStore.register_document for the collision guard this
    is paired with.
    """
    safe_id(company_id, label="company_id")
    payload = f"{company_id}\x00{doc_type}\x00{content_key}"
    return f"doc_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


class DocumentContentStore:
    """Content-addressed cache of parsed document text, plus a
    company/doc_type -> doc_id directory for cross-run citation
    resolution.

    A deliberate departure from every other store in this app: it uses
    stdlib sqlite3, the first database anywhere in this codebase, where
    every other store advertises "no database" and means it. That rule
    protects *user-authored* state (a run's manifest, an engagement's
    audit trail) that cannot be regenerated if lost or corrupted. This
    store holds only *derived* state -- deleting content.db costs nothing
    but re-parsing time. A single file also gives one consistent lookup
    across three axes (content hash -> text, doc_id -> document, file
    stat -> content hash) that a directory of cache files would need three
    hand-rolled indexes to match, with atomicity across full_text and
    page_breaks landing together or not at all -- both matter because
    arp/grounding.py resolves a citation's page from page_breaks and must
    never see one without the other.

    No lock() method, unlike RunStore/EngagementStore, and deliberately
    so: every write here is an idempotent, content-addressed insert of a
    value that's a pure function of its key (INSERT ... ON CONFLICT DO
    NOTHING). There is no read-modify-write invariant to protect -- two
    workers parsing the same file concurrently compute identical text, and
    the losing insert is a no-op. A lost write costs one re-parse, not a
    lost update, which is the whole distinction from the stores that do
    need KeyedLock. SQLite's own write transaction plus busy_timeout
    already serializes writers across processes, which a threading.RLock
    couldn't do anyway.

    Connections are opened per operation and always closed in `finally` --
    never shared across threads or held on an instance. That's what makes
    `check_same_thread` (sqlite3's default-True safety check) a non-issue
    without ever needing to pass check_same_thread=False: every connection
    is created, used, and closed on the one thread that opened it. Connect
    overhead (tens to low hundreds of microseconds) is negligible next to
    a parse (seconds) or even a multi-MB row read (single-digit ms).

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

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5.0)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    # --- content identity -------------------------------------------------

    @staticmethod
    def _hash_file_bytes(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def content_key_for_file(self, path: Path) -> str:
        """Stable content identity for a local file: a sha256 of the file
        *bytes* -- not arp.schemas.common.SourceDocument.sha256, which
        hashes the extracted *text* and is therefore both circular as a
        cache key (you'd have to parse to compute it) and parser-version
        dependent. A (path, size, mtime_ns) fast path avoids re-hashing an
        unchanged file on every fetch; deliberately not the identity
        itself, so a byte-identical re-download (which bumps mtime) still
        resolves to the same content_key and the same doc_id.
        """
        if not self.enabled:
            return self._hash_file_bytes(path)

        stat = path.stat()
        abs_path = str(path.resolve())
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT content_key FROM file_identity WHERE abs_path=? AND size_bytes=? AND mtime_ns=?",
                (abs_path, stat.st_size, stat.st_mtime_ns),
            ).fetchone()
            if row is not None:
                return row[0]
            content_key = self._hash_file_bytes(path)
            conn.execute(
                "INSERT OR REPLACE INTO file_identity (abs_path, size_bytes, mtime_ns, content_key, seen_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (abs_path, stat.st_size, stat.st_mtime_ns, content_key, now_iso()),
            )
            conn.commit()
            return content_key
        finally:
            conn.close()

    # --- parsed-text cache --------------------------------------------------

    def _lookup_parsed(self, conn: sqlite3.Connection, content_key: str, parser_version: str) -> ParsedContent | None:
        row = conn.execute(
            "SELECT page_breaks, full_text, text_sha256 FROM parsed_content WHERE content_key=? AND parser_version=?",
            (content_key, parser_version),
        ).fetchone()
        if row is None:
            return None
        page_breaks_json, full_text, text_sha256 = row
        try:
            page_breaks = json.loads(page_breaks_json)
        except json.JSONDecodeError:
            # Corrupt row -- treat as a miss (house convention, see
            # arp/llm/cache.py) and self-heal by deleting it, since unlike
            # a file-based cache a stale row here would otherwise
            # permanently block a fresh INSERT under the same unique key.
            logger.warning("Corrupt page_breaks for content_key=%s parser_version=%s; discarding", content_key, parser_version)
            conn.execute(
                "DELETE FROM parsed_content WHERE content_key=? AND parser_version=?", (content_key, parser_version)
            )
            conn.commit()
            return None
        return ParsedContent(content_key=content_key, full_text=full_text, page_breaks=page_breaks, text_sha256=text_sha256)

    def get_or_compute(
        self,
        content_key: str,
        *,
        key_kind: str,
        parser_version: str,
        source_suffix: str,
        byte_size: int,
        compute: Callable[[], tuple[str, list[int]]],
    ) -> ParsedContent:
        """Generic content-addressed parse cache: given an already-known
        content_key (a local file's byte hash via content_key_for_file, or
        e.g. an EDGAR accession-derived key), returns cached parsed text on
        a hit or calls `compute()` and caches the result on a miss.
        `compute` is injected rather than imported, so this store never
        depends on pymupdf4llm/trafilatura and is testable with a
        call-counting fake.
        """
        if self.enabled:
            conn = self._connect()
            try:
                cached = self._lookup_parsed(conn, content_key, parser_version)
                if cached is not None:
                    return cached
            finally:
                conn.close()

        text, page_breaks = compute()
        text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        result = ParsedContent(content_key=content_key, full_text=text, page_breaks=page_breaks, text_sha256=text_sha256)

        if self.enabled and len(text) <= _MAX_CACHED_CHARS:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO parsed_content "
                    "(content_key, key_kind, parser_version, source_suffix, full_text, page_breaks, text_sha256, "
                    " char_len, byte_size, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(content_key, parser_version) DO NOTHING",
                    (
                        content_key,
                        key_kind,
                        parser_version,
                        source_suffix,
                        text,
                        json.dumps(page_breaks),
                        text_sha256,
                        len(text),
                        byte_size,
                        now_iso(),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return result

    def get_or_parse(
        self, path: Path, *, parser_version: str, parse: Callable[[Path], tuple[str, list[int]]]
    ) -> ParsedContent:
        """File-specific convenience wrapper over get_or_compute: derives
        the content_key from the file's bytes (via content_key_for_file)
        and the parse callable from the path."""
        content_key = self.content_key_for_file(path)
        return self.get_or_compute(
            content_key,
            key_kind="file_bytes",
            parser_version=parser_version,
            source_suffix=path.suffix.lower(),
            byte_size=path.stat().st_size,
            compute=lambda: parse(path),
        )

    # --- document directory (doc_id -> company/doc_type/content) -----------

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
                "SELECT doc_id, company_id, doc_type, content_key, title, local_path, source_url "
                "FROM documents WHERE doc_id=?",
                (doc_id,),
            ).fetchone()
            if row is None:
                return None
            return StoredDocumentRef(*row)
        finally:
            conn.close()

    # --- operator surface (arp documents ... CLI, phase 4) ------------------

    def stats(self) -> dict:
        if not self.enabled:
            return {"enabled": False}
        conn = self._connect()
        try:
            row_count, total_chars, distinct_versions = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(char_len), 0), COUNT(DISTINCT parser_version) FROM parsed_content"
            ).fetchone()
            doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            return {
                "enabled": True,
                "cached_documents": row_count,
                "total_chars": total_chars,
                "distinct_parser_versions": distinct_versions,
                "registered_documents": doc_count,
                "db_path": str(self._db_path),
            }
        finally:
            conn.close()

    def prune(self, *, keep_parser_version: str) -> int:
        """Deletes parsed_content rows orphaned by a parser upgrade
        (anything not matching the current parser_version) and reclaims
        the space. Orphaned rows are harmless -- nothing reads them, since
        every lookup is keyed on the current parser_version -- so this is
        purely a housekeeping operation, not something a run ever needs to
        call. VACUUM needs exclusive access to the file; don't run this
        against a live API process."""
        if not self.enabled:
            return 0
        conn = self._connect()
        try:
            cur = conn.execute("DELETE FROM parsed_content WHERE parser_version != ?", (keep_parser_version,))
            deleted = cur.rowcount
            conn.commit()
            conn.execute("VACUUM")
            return deleted
        finally:
            conn.close()
