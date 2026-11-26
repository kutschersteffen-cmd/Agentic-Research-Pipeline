"""The Theme Radar signal store: every item an Emerging Themes scan fetches, kept once per content hash in
`signal_items`, with its embedding cached in `chunk_embeddings` (`chunk_id = "signal:" + content_hash`)."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from arp.schemas.emerging_themes import SIGNAL_SOURCE_TYPE, RawMention, SignalItem, SignalSourceType
from arp.storage.postgres import get_engine

logger = logging.getLogger(__name__)


def content_hash(url: str, title: str, text: str) -> str:
    def norm(s: str) -> str:
        return " ".join(s.split())

    return hashlib.sha256(f"{url}\n{norm(title)}\n{norm(text)}".encode()).hexdigest()


def _parse_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


class SignalStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._engine = get_engine(dsn)

    def add_items(self, items: list[RawMention], *, seen_at: datetime | None = None) -> int:
        """Stores each item whose hash is new; for a stored hash only moves `last_seen_at`. Returns rows inserted."""
        from sqlalchemy import update
        from sqlalchemy.dialects.postgresql import insert
        from sqlalchemy.orm import Session

        from arp.storage.postgres_models import SignalItemModel

        seen_at = seen_at or datetime.now(UTC)
        rows: dict[str, dict] = {}
        for m in items:
            h = content_hash(m.url, m.title, m.text)
            if h in rows:
                continue
            published_at = _parse_time(m.published_at)
            rows[h] = {
                "content_hash": h, "source": m.source_type.value, "source_type": SIGNAL_SOURCE_TYPE[m.source_type].value,
                "title": m.title, "text": m.text, "url": m.url, "raw_entity_names": m.raw_entity_names,
                "published_at": published_at,
                # a published_at that does not parse is stored as null, flagged estimated
                "published_at_is_estimated": m.published_at_is_estimated or (m.published_at is not None and published_at is None),
                "item_at": published_at or seen_at, "first_seen_at": seen_at, "last_seen_at": seen_at,
            }
        if not rows:
            return 0
        with Session(self._engine) as session:
            inserted = set(session.scalars(
                insert(SignalItemModel).values(list(rows.values())).on_conflict_do_nothing()
                .returning(SignalItemModel.content_hash)
            ))
            seen_before = set(rows) - inserted
            if seen_before:
                session.execute(
                    update(SignalItemModel).where(SignalItemModel.content_hash.in_(seen_before)).values(last_seen_at=seen_at)
                )
            session.commit()
        if inserted:
            self._embed([rows[h] for h in rows if h in inserted])
        return len(inserted)

    def _embed(self, rows: list[dict]) -> None:
        from arp.retrieval import embeddings
        from arp.storage.postgres_embeddings import PgVectorEmbeddingsStore

        try:
            vectors = embeddings.embed_texts([f"{r['title']}\n{r['text']}" for r in rows])
            PgVectorEmbeddingsStore(self._dsn).store_embeddings(
                {"signal:" + r["content_hash"]: v for r, v in zip(rows, vectors, strict=True)}, embeddings.EMBED_MODEL_NAME
            )
        except Exception:  # noqa: BLE001 - the items stay stored, without embeddings
            logger.exception("Embedding %d signal items failed", len(rows))

    def read_items(
        self, *, since: datetime, until: datetime | None = None, source_types: list[SignalSourceType] | None = None
    ) -> list[SignalItem]:
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from arp.storage.postgres_models import SignalItemModel as M

        query = select(M).where(M.item_at >= since)
        if until is not None:
            query = query.where(M.item_at < until)
        if source_types is not None:
            query = query.where(M.source_type.in_([t.value for t in source_types]))
        with Session(self._engine) as session:
            rows = session.scalars(query.order_by(M.item_at, M.content_hash)).all()
            return [
                SignalItem(
                    content_hash=r.content_hash, source=r.source, source_type=r.source_type, title=r.title, text=r.text,
                    url=r.url, raw_entity_names=r.raw_entity_names,
                    published_at=_iso(r.published_at) if r.published_at else None,
                    published_at_is_estimated=r.published_at_is_estimated, item_at=_iso(r.item_at),
                    first_seen_at=_iso(r.first_seen_at), last_seen_at=_iso(r.last_seen_at),
                )
                for r in rows
            ]
