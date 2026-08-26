from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from arp.schemas.common import now_iso

logger = logging.getLogger(__name__)

# A row's payload is never UPDATEd, only inserted once per
# (content_key, parser_version); a parser upgrade orphans old rows rather
# than touching them (see arp/ingestion/local_files.py::parser_version).
# Deliberately a normal rowid table, not WITHOUT ROWID -- full_text can be
# several MB, and forcing that into the PK's own B-tree (what WITHOUT
# ROWID does) causes overflow-page churn a separate rowid table avoids.
SCHEMA = """
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


class ParsedContentCache:
    """Content-addressed cache of parsed document text (the parsed_content
    table), plus a file-stat fast path (file_identity) that exists purely
    to avoid re-hashing an unchanged file on every fetch -- not an
    independent concern, just this cache's own identity-lookup detail.

    One of DocumentContentStore's three collaborators (see
    arp/storage/document_store.py for why they share one SQLite file and
    connection recipe). No lock() method, deliberately: every write here
    is an idempotent, content-addressed insert of a value that's a pure
    function of its key (INSERT ... ON CONFLICT DO NOTHING) -- a lost
    write under concurrent writers costs one re-parse, not a lost update.
    """

    def __init__(self, connect: Callable[[], sqlite3.Connection], enabled: bool) -> None:
        self._connect = connect
        self.enabled = enabled

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

    def lookup(self, content_key: str, parser_version: str) -> ParsedContent | None:
        """Read-only half of get_or_compute: checks the cache and returns
        immediately, without a compute callable. For a caller that must
        decide whether to do expensive I/O (e.g. an async network fetch,
        which a synchronous `compute` callable can't express) *before*
        paying for it -- unlike get_or_compute, which only avoids the
        compute() call itself, not whatever setup a caller did to prepare
        for it. See EdgarDocumentSource for the motivating use.
        """
        if not self.enabled:
            return None
        conn = self._connect()
        try:
            return self._lookup_parsed(conn, content_key, parser_version)
        finally:
            conn.close()

    def store(
        self,
        content_key: str,
        *,
        key_kind: str,
        parser_version: str,
        source_suffix: str,
        byte_size: int,
        text: str,
        page_breaks: list[int],
    ) -> ParsedContent:
        """Write-only half of get_or_compute, for a caller (see lookup())
        that already has text + page_breaks in hand from its own
        computation."""
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
        `compute` is injected rather than imported, so this cache never
        depends on docling/trafilatura and is testable with a
        call-counting fake.
        """
        cached = self.lookup(content_key, parser_version)
        if cached is not None:
            return cached
        text, page_breaks = compute()
        return self.store(
            content_key,
            key_kind=key_kind,
            parser_version=parser_version,
            source_suffix=source_suffix,
            byte_size=byte_size,
            text=text,
            page_breaks=page_breaks,
        )

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

    def list_cached(self, offset: int, limit: int) -> tuple[list[dict], int]:
        """Lists parsed_content rows newest-first for the "view stored
        extractions" browser, deliberately excluding full_text/page_breaks
        (rows can be multi-MB) -- callers fetch a row's text on demand via
        get_full_text once the user picks it."""
        if not self.enabled:
            return [], 0
        conn = self._connect()
        try:
            total = conn.execute("SELECT COUNT(*) FROM parsed_content").fetchone()[0]
            rows = conn.execute(
                "SELECT id, content_key, key_kind, parser_version, source_suffix, char_len, byte_size, "
                "text_sha256, created_at FROM parsed_content ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            columns = [
                "id", "content_key", "key_kind", "parser_version", "source_suffix", "char_len", "byte_size",
                "text_sha256", "created_at",
            ]
            return [dict(zip(columns, row)) for row in rows], total
        finally:
            conn.close()

    def get_full_text(self, row_id: int) -> ParsedContent | None:
        """Fetches one cached row's full text + page_breaks by its rowid
        (as returned by list_cached), for the "view stored extractions"
        browser's expand-a-row action. Same corrupt-JSON self-heal as
        _lookup_parsed, keyed by id instead of (content_key, parser_version)."""
        if not self.enabled:
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT content_key, page_breaks, full_text, text_sha256 FROM parsed_content WHERE id=?",
                (row_id,),
            ).fetchone()
            if row is None:
                return None
            content_key, page_breaks_json, full_text, text_sha256 = row
            try:
                page_breaks = json.loads(page_breaks_json)
            except json.JSONDecodeError:
                logger.warning("Corrupt page_breaks for parsed_content row id=%s; discarding", row_id)
                conn.execute("DELETE FROM parsed_content WHERE id=?", (row_id,))
                conn.commit()
                return None
            return ParsedContent(content_key=content_key, full_text=full_text, page_breaks=page_breaks, text_sha256=text_sha256)
        finally:
            conn.close()

    def stats(self, conn: sqlite3.Connection) -> dict:
        """Takes an already-open connection -- called by
        DocumentContentStore.stats() as part of one cross-cutting operator
        view alongside the other collaborators' counts."""
        row_count, total_chars, distinct_versions = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(char_len), 0), COUNT(DISTINCT parser_version) FROM parsed_content"
        ).fetchone()
        return {"cached_documents": row_count, "total_chars": total_chars, "distinct_parser_versions": distinct_versions}

    def prune(self, *, keep_parser_version: str | Iterable[str]) -> int:
        """Deletes parsed_content rows orphaned by a parser upgrade
        (anything not matching a current parser_version) and reclaims the
        space. Orphaned rows are harmless -- nothing reads them, since
        every lookup is keyed on the current parser_version -- so this is
        purely a housekeeping operation, not something a run ever needs to
        call. VACUUM needs exclusive access to the file; don't run this
        against a live API process.

        Accepts either a single version string or an iterable of them:
        this table holds rows from more than one producer (local file
        parsing and EDGAR filing extraction each stamp their own
        parser_version), so pruning after just one of them upgrades must
        pass *all* currently-active versions, not just the one that
        changed -- otherwise this would delete the other producer's still-
        current cache along with the truly stale rows.
        """
        if not self.enabled:
            return 0
        versions = [keep_parser_version] if isinstance(keep_parser_version, str) else list(keep_parser_version)
        if not versions:
            raise ValueError("keep_parser_version must not be empty")
        conn = self._connect()
        try:
            placeholders = ",".join("?" for _ in versions)
            cur = conn.execute(f"DELETE FROM parsed_content WHERE parser_version NOT IN ({placeholders})", versions)
            deleted = cur.rowcount
            conn.commit()
            conn.execute("VACUUM")
            return deleted
        finally:
            conn.close()
