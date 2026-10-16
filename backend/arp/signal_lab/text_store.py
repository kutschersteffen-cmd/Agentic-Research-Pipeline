from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from arp.db.models import TextItem
from arp.db.session import transaction
from arp.signal_lab.times import content_hash_of, normalise_time

_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class TextRecord(BaseModel):
    item_id: str
    source: str  # "tr_news" | "edgar" | "transcript" by convention
    source_item_id: str
    company_id: str | None
    event_time: str
    knowledge_time: str
    revision_time: str | None
    content_hash: str
    title: str
    body: str
    source_url: str | None


def make_record(
    *,
    source: str,
    source_item_id: str,
    company_id: str | None,
    event_time: str,
    knowledge_time: str,
    title: str,
    body: str,
    revision_time: str | None = None,
    source_url: str | None = None,
) -> TextRecord:
    content_hash = content_hash_of(title, body)
    digest = hashlib.sha256(f"{source}|{source_item_id}|{content_hash}".encode()).hexdigest()
    return TextRecord(
        item_id=f"txt_{digest[:16]}",
        source=source,
        source_item_id=source_item_id,
        company_id=company_id,
        event_time=normalise_time(event_time),
        knowledge_time=normalise_time(knowledge_time),
        revision_time=normalise_time(revision_time) if revision_time else None,
        content_hash=content_hash,
        title=title,
        body=body,
        source_url=source_url,
    )


def _dt(value: str) -> datetime:
    return datetime.strptime(normalise_time(value), _FORMAT).replace(tzinfo=UTC)


def _s(value: datetime) -> str:
    return value.astimezone(UTC).strftime(_FORMAT)


class TextStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def add(self, rec: TextRecord) -> bool:
        values = rec.model_dump()
        for key in ("event_time", "knowledge_time"):
            values[key] = _dt(values[key])
        values["revision_time"] = _dt(rec.revision_time) if rec.revision_time else None
        stmt = insert(TextItem).values(**values).on_conflict_do_nothing(constraint="uq_text_items_version").returning(TextItem.item_id)
        with transaction(self._dsn) as s:
            return s.scalar(stmt) is not None

    def items(
        self,
        *,
        company_id: str | None = None,
        event_from: str | None = None,
        event_to: str | None = None,
        known_by: str | None = None,
    ) -> list[TextRecord]:
        visible = select(
            TextItem,
            func.row_number()
            .over(
                partition_by=(TextItem.source, TextItem.source_item_id),
                order_by=(TextItem.knowledge_time.desc(), TextItem.item_id.desc()),
            )
            .label("rn"),
        )
        if known_by is not None:
            visible = visible.where(TextItem.knowledge_time <= _dt(known_by))
        latest = visible.subquery()
        row = latest.c
        q = select(latest).where(row.rn == 1)
        if company_id is not None:
            q = q.where(row.company_id == company_id)
        if event_from is not None:
            q = q.where(row.event_time >= _dt(event_from))
        if event_to is not None:
            q = q.where(row.event_time <= _dt(event_to))
        q = q.order_by(row.event_time, row.item_id)
        with transaction(self._dsn) as s:
            rows = s.execute(q).mappings().all()
        return [
            TextRecord(
                **{k: rec[k] for k in ("item_id", "source", "source_item_id", "company_id", "content_hash", "title", "body", "source_url")},
                event_time=_s(rec["event_time"]),
                knowledge_time=_s(rec["knowledge_time"]),
                revision_time=_s(rec["revision_time"]) if rec["revision_time"] else None,
            )
            for rec in rows
        ]

    def latest_revision_time(self, source: str, source_item_id: str) -> str | None:
        q = select(func.max(TextItem.revision_time)).where(
            TextItem.source == source, TextItem.source_item_id == source_item_id
        )
        with transaction(self._dsn) as s:
            latest = s.scalar(q)
        return _s(latest) if latest else None
