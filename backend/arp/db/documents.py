"""Document registry: doc_id -> (company, doc_type, content_key) in the Postgres `documents` table, for
cross-run citation resolution. Callers pass the universe company id; it is resolved to the company uuid
(created if unknown) and also kept in `universe_id` so refs keep exposing the id callers know.
Parsed text stays in the SQLite content cache, so readiness asks the caller which keys are parsed."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from arp.db.companies import ensure_universe_company, lookup
from arp.db.models import Document, IdScheme
from arp.db.session import transaction
from arp.schemas.common import new_id
from arp.storage.safe_path import safe_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StoredDocumentRef:
    """One registered document. `company_id` is the universe company id callers registered it under."""

    doc_id: str
    company_id: str
    doc_type: str
    content_key: str
    title: str
    local_path: str | None
    source_url: str | None
    storage_uri: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    family_id: str | None = None
    version: int | None = None
    supersedes: str | None = None
    published_at: str | None = None
    identity_confidence: float | None = None
    identity_review: int | None = None


def derive_doc_id(company_id: str, doc_type: str, content_key: str) -> str:
    """A document's identity is (company, doc_type, bytes), so its id is a deterministic hash of those three
    (not parser_version: a citation keeps resolving across a parser upgrade). 16 hex chars (64 bits) keeps
    the birthday-collision chance negligible; register_document still guards against one."""
    safe_id(company_id, label="company_id")
    payload = f"{company_id}\x00{doc_type}\x00{content_key}"
    return f"doc_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def get_document(session: Session, doc_id: str) -> Document | None:
    return session.get(Document, doc_id)


def _ref(d: Document) -> StoredDocumentRef:
    return StoredDocumentRef(
        doc_id=d.doc_id,
        company_id=d.universe_id or str(d.company_id),
        doc_type=d.doc_type,
        content_key=d.content_key,
        title=d.title,
        local_path=d.local_path,
        source_url=d.source_url,
        storage_uri=d.storage_uri,
        first_seen_at=d.first_seen_at.isoformat(),
        last_seen_at=d.last_seen_at.isoformat(),
        family_id=d.family_id,
        version=d.version,
        supersedes=d.supersedes,
        published_at=d.published_at.isoformat() if d.published_at else None,
        identity_confidence=d.identity_confidence,
        identity_review=None if d.identity_review is None else int(d.identity_review),
    )


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


class DocumentRegistry:
    """One of DocumentContentStore's collaborators (see arp/storage/document_store.py)."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

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
        """Records doc_id -> (company, doc_type, content_key). Returns the doc_id stored under: the one passed
        in, unless it already maps to a different (company, content_key) -- a collision, logged and answered
        with a fresh random id rather than overwriting the existing mapping."""
        safe_id(company_id, label="company_id")
        with transaction(self._dsn) as session:
            uuid = ensure_universe_company(session, company_id)
            existing = session.get(Document, doc_id)
            if existing is not None and (existing.company_id, existing.content_key) != (uuid, content_key):
                logger.error(
                    "doc_id collision: %s already maps to company=%s content_key=%s; assigning a fresh id for "
                    "company_id=%s content_key=%s instead",
                    doc_id, existing.company_id, existing.content_key, company_id, content_key,
                )
                doc_id = new_id("doc")
            now = datetime.now(UTC)
            stmt = insert(Document).values(
                doc_id=doc_id, company_id=uuid, universe_id=company_id, doc_type=doc_type, content_key=content_key,
                title=title, local_path=local_path, source_url=source_url, first_seen_at=now, last_seen_at=now,
            )
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[Document.doc_id],
                    set_={c: stmt.excluded[c] for c in ("last_seen_at", "local_path", "title", "content_key")},
                )
            )
            return doc_id

    def resolve_document(self, doc_id: str) -> StoredDocumentRef | None:
        with transaction(self._dsn) as session:
            d = get_document(session, doc_id)
            return _ref(d) if d else None

    def set_storage_uri(self, doc_id: str, storage_uri: str) -> None:
        """Records where the document's original bytes landed in object storage, after the fact."""
        with transaction(self._dsn) as session:
            session.execute(update(Document).where(Document.doc_id == doc_id).values(storage_uri=storage_uri))

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
        with transaction(self._dsn) as session:
            session.execute(
                update(Document)
                .where(Document.doc_id == doc_id)
                .values(
                    family_id=family_id, version=version, supersedes=supersedes, published_at=_date(published_at),
                    identity_confidence=confidence, identity_review=needs_review,
                )
            )

    def list_family(self, family_id: str) -> list[StoredDocumentRef]:
        with transaction(self._dsn) as session:
            rows = session.scalars(
                select(Document)
                .where(Document.family_id == family_id)
                .order_by(Document.version.asc().nulls_first(), Document.doc_id)
            )
            return [_ref(d) for d in rows]

    def list_by_content_keys(self, content_keys: list[str]) -> dict[str, StoredDocumentRef]:
        """Batch lookup for display enrichment. Content-addressed: if several documents share a content_key
        the last row read wins."""
        if not content_keys:
            return {}
        with transaction(self._dsn) as session:
            rows = session.scalars(select(Document).where(Document.content_key.in_(content_keys)).order_by(Document.doc_id))
            return {d.content_key: _ref(d) for d in rows}

    def list_all(self) -> list[StoredDocumentRef]:
        """Every registered document, for backfill/reindex; no pagination."""
        with transaction(self._dsn) as session:
            return [_ref(d) for d in session.scalars(select(Document).order_by(Document.doc_id))]

    def readiness_by_company(
        self, company_ids: list[str], parsed_keys: Callable[[list[str]], set[str]] | None = None
    ) -> dict[str, dict]:
        """Per universe company: registered documents, how many have parsed text (`parsed_keys` says which
        content keys do -- parsed text is in the SQLite cache), doc types and latest last_seen_at.
        Companies with no rows are absent."""
        if not company_ids:
            return {}
        with transaction(self._dsn) as session:
            # filter by company uuid (not the display-only universe_id) so a merged company's documents follow it
            owners: dict = {}
            for universe_id in company_ids:
                uuid = lookup(session, IdScheme.UNIVERSE, universe_id)
                if uuid is not None:
                    owners.setdefault(uuid, []).append(universe_id)
            rows = session.execute(
                select(Document.company_id, Document.doc_type, Document.content_key, Document.last_seen_at).where(
                    Document.company_id.in_(owners)
                )
            ).all()
        parsed = parsed_keys(sorted({r.content_key for r in rows})) if parsed_keys else set()
        out: dict[str, dict] = {}
        for uuid, doc_type, content_key, last_seen in rows:
            for company_id in owners[uuid]:
                e = out.setdefault(
                    company_id, {"registered": 0, "parsed": 0, "doc_types": set(), "last_seen_at": last_seen}
                )
                e["registered"] += 1
                e["parsed"] += content_key in parsed
                e["doc_types"].add(doc_type)
                e["last_seen_at"] = max(e["last_seen_at"], last_seen)
        for e in out.values():
            e["doc_types"] = sorted(e["doc_types"])
            e["last_seen_at"] = e["last_seen_at"].isoformat()
        return out

    def stats(self) -> dict:
        with transaction(self._dsn) as session:
            return {"registered_documents": session.scalar(select(func.count()).select_from(Document))}
