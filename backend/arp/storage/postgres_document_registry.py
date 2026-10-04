"""Postgres form of DocumentRegistry (arp/storage/document_registry.py),
authoritative when Settings.embeddings_backend == "postgres" with a
postgres_dsn. Same public methods, return types and semantics as the SQLite
one; the rows live in `document_registry` (DocumentRegistryModel), the table
the read-only projection also writes. Parsed text stays in SQLite (derived
cache), so `readiness_by_company` asks the caller which content keys have a
parsed row.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import cache
from pathlib import Path

from arp.schemas.common import new_id, now_iso
from arp.storage.document_registry import StoredDocumentRef
from arp.storage.postgres import ensure_schema, get_engine
from arp.storage.safe_path import safe_id

logger = logging.getLogger(__name__)

_FIELDS = tuple(StoredDocumentRef.__dataclass_fields__)


@cache
def _ensure_schema_once(dsn: str) -> None:
    ensure_schema(dsn)


def _ref(row) -> StoredDocumentRef:
    return StoredDocumentRef(**{f: getattr(row, f) for f in _FIELDS})


class PgDocumentRegistry:
    def __init__(self, dsn: str, enabled: bool, parsed_keys: Callable[[list[str]], set[str]]) -> None:
        self._dsn = dsn
        self.enabled = enabled
        self._parsed_keys = parsed_keys
        _ensure_schema_once(dsn)
        self._engine = get_engine(dsn)

    def _session(self):
        from sqlalchemy.orm import Session

        return Session(self._engine)

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
        """Same contract as DocumentRegistry.register_document, including the
        collision guard (an existing doc_id mapping to a different
        (company_id, content_key) gets a fresh random id instead)."""
        if not self.enabled:
            return doc_id
        safe_id(company_id, label="company_id")
        from sqlalchemy.dialects.postgresql import insert

        from arp.storage.postgres_models import DocumentRegistryModel as M

        with self._session() as session:
            existing = session.get(M, doc_id)
            if existing is not None and (existing.company_id, existing.content_key) != (company_id, content_key):
                logger.error(
                    "doc_id collision: %s already maps to company_id=%s content_key=%s; assigning a fresh id for "
                    "company_id=%s content_key=%s instead",
                    doc_id,
                    existing.company_id,
                    existing.content_key,
                    company_id,
                    content_key,
                )
                doc_id = new_id("doc")
            now = now_iso()
            stmt = insert(M).values(
                doc_id=doc_id,
                company_id=company_id,
                doc_type=doc_type,
                content_key=content_key,
                title=title,
                local_path=local_path,
                source_url=source_url,
                first_seen_at=now,
                last_seen_at=now,
            )
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[M.doc_id],
                    set_={
                        "last_seen_at": stmt.excluded.last_seen_at,
                        "local_path": stmt.excluded.local_path,
                        "title": stmt.excluded.title,
                        "content_key": stmt.excluded.content_key,
                    },
                )
            )
            session.commit()
            return doc_id

    def resolve_document(self, doc_id: str) -> StoredDocumentRef | None:
        if not self.enabled:
            return None
        from arp.storage.postgres_models import DocumentRegistryModel as M

        with self._session() as session:
            row = session.get(M, doc_id)
            return _ref(row) if row is not None else None

    def set_storage_uri(self, doc_id: str, storage_uri: str) -> None:
        if not self.enabled:
            return
        from sqlalchemy import update

        from arp.storage.postgres_models import DocumentRegistryModel as M

        with self._session() as session:
            session.execute(update(M).where(M.doc_id == doc_id).values(storage_uri=storage_uri))
            session.commit()

    def set_identity(
        self,
        doc_id: str,
        *,
        family_id: str,
        version: int,
        supersedes: str | None,
        published_at: str | None,
        confidence: float,
        needs_review: bool,
    ) -> None:
        if not self.enabled:
            return
        from sqlalchemy import update

        from arp.storage.postgres_models import DocumentRegistryModel as M

        with self._session() as session:
            session.execute(
                update(M)
                .where(M.doc_id == doc_id)
                .values(
                    family_id=family_id,
                    version=version,
                    supersedes=supersedes,
                    published_at=published_at,
                    identity_confidence=confidence,
                    identity_review=int(needs_review),
                )
            )
            session.commit()

    def list_family(self, family_id: str) -> list[StoredDocumentRef]:
        if not self.enabled:
            return []
        from sqlalchemy import select

        from arp.storage.postgres_models import DocumentRegistryModel as M

        with self._session() as session:
            rows = session.scalars(
                select(M).where(M.family_id == family_id).order_by(M.version.asc().nulls_first(), M.doc_id)
            )
            return [_ref(r) for r in rows]

    def list_by_content_keys(self, content_keys: list[str]) -> dict[str, StoredDocumentRef]:
        """Content-addressed; if several documents share a content_key the
        last row read wins (display-only enrichment), as in SQLite."""
        if not self.enabled or not content_keys:
            return {}
        from sqlalchemy import select

        from arp.storage.postgres_models import DocumentRegistryModel as M

        with self._session() as session:
            rows = session.scalars(select(M).where(M.content_key.in_(content_keys)).order_by(M.doc_id))
            return {r.content_key: _ref(r) for r in rows}

    def list_all(self) -> list[StoredDocumentRef]:
        if not self.enabled:
            return []
        from sqlalchemy import select

        from arp.storage.postgres_models import DocumentRegistryModel as M

        with self._session() as session:
            return [_ref(r) for r in session.scalars(select(M).order_by(M.doc_id))]

    def readiness_by_company(self, company_ids: list[str]) -> dict[str, dict]:
        """Per company: registered documents, how many have a parsed row
        (asked of `parsed_keys`, since parsed text is in SQLite), doc types
        and latest last_seen_at. Companies with no rows are absent."""
        if not self.enabled or not company_ids:
            return {}
        from sqlalchemy import select

        from arp.storage.postgres_models import DocumentRegistryModel as M

        with self._session() as session:
            rows = session.execute(
                select(M.company_id, M.doc_type, M.content_key, M.last_seen_at).where(M.company_id.in_(company_ids))
            ).all()
        parsed = self._parsed_keys(sorted({r.content_key for r in rows}))
        out: dict[str, dict] = {}
        for company_id, doc_type, content_key, last_seen in rows:
            e = out.setdefault(
                company_id, {"registered": 0, "parsed": 0, "doc_types": set(), "last_seen_at": last_seen}
            )
            e["registered"] += 1
            e["parsed"] += content_key in parsed
            e["doc_types"].add(doc_type)
            e["last_seen_at"] = max(e["last_seen_at"], last_seen)
        for e in out.values():
            e["doc_types"] = sorted(e["doc_types"])
        return out

    def stats(self) -> dict:
        if not self.enabled:
            return {"registered_documents": 0}
        from sqlalchemy import func, select

        from arp.storage.postgres_models import DocumentRegistryModel as M

        with self._session() as session:
            return {"registered_documents": session.scalar(select(func.count()).select_from(M))}


def copy_sqlite_registry(store_dir: Path, dsn: str) -> int:
    """Backfill: copies SQLite registry rows not yet in Postgres, keeping
    their first/last_seen_at, storage_uri and identity columns; never
    overwrites a Postgres row (it may be newer, written after cutover).
    Idempotent. Returns the number of rows copied."""
    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy.orm import Session

    from arp.storage.document_store import DocumentContentStore
    from arp.storage.postgres_models import DocumentRegistryModel as M

    _ensure_schema_once(dsn)
    refs = DocumentContentStore(store_dir).list_all_documents()  # SQLite DocumentRegistry.list_all
    copied = 0
    with Session(get_engine(dsn)) as session:
        for ref in refs:
            stmt = insert(M).values(**{f: getattr(ref, f) for f in _FIELDS})
            stmt = stmt.on_conflict_do_nothing(index_elements=[M.doc_id]).returning(M.doc_id)
            copied += session.execute(stmt).first() is not None
        session.commit()
    return copied


@cache
def warn_if_unmigrated(dsn: str, sqlite_db: Path) -> None:
    """Logs an ERROR (once per process) when the Postgres registry is empty
    but the SQLite one in `sqlite_db` has rows: a deployment switched to
    embeddings_backend=postgres without running the one-time copy."""
    import sqlite3
    from contextlib import closing

    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from arp.storage.postgres_models import DocumentRegistryModel as M

    try:
        with closing(sqlite3.connect(sqlite_db)) as conn:
            local = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    except sqlite3.Error:
        return
    if not local:
        return
    with Session(get_engine(dsn)) as session:
        if session.scalar(select(func.count()).select_from(M)):
            return
    logger.error(
        "The Postgres document registry is empty but %s has %d registered documents: they are invisible until "
        "copied. Run `arp documents migrate-registry`.",
        sqlite_db,
        local,
    )
