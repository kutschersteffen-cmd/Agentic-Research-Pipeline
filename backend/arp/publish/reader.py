"""As-of reads over published facts and the change-event outbox (E76).

A fact is visible as of `b` when `valid_from <= b` and it was not closed by then (`valid_to` is
null or `> b`). `valid_from` is the publication time, so a fact published after the as-of point
is never shown. All timestamps are fixed-width UTC strings, so string comparison orders them.

`valid_from` and `valid_to` come from the publisher's clock (`ts_now`), not the reader's.

Outbox events (`fact_events`, ordered by `event_id`). `read_events` by id is the delivery cursor
(ids follow commit order, see `PublishStore._commit`); `events_since` is only a time filter:
- `published` / `restated`: a new fact version; `release_id` is the publishing release.
- `withdrawn`: the closed fact; `release_id` is the release being withdrawn.
- `restored`: the copy of an earlier value that becomes current again; `release_id` is the
  SOURCE release of that value, not the release being withdrawn.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, date, datetime

from arp.publish.facts import Fact, FactEvent, PublishStore, fact_key
from arp.publish.facts import _fact as _fact_from_row


def as_of_bound(as_of: str) -> str:
    """A date `YYYY-MM-DD` (end of that day, UTC) or an ISO datetime (naive means UTC)."""
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
            return f"{date.fromisoformat(as_of).isoformat()}T23:59:59.999999+00:00"
        if not re.match(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", as_of):
            raise ValueError(as_of)
        dt = datetime.fromisoformat(as_of)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat(timespec="microseconds")
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f"bad as_of: {as_of!r}") from None


def visible(facts: Iterable[Fact], as_of: str) -> list[Fact]:
    b = as_of_bound(as_of)
    best: dict = {}
    for f in facts:
        if f.valid_from <= b and (f.valid_to is None or f.valid_to > b):
            k = fact_key(f)
            if k not in best or f.version > best[k].version:
                best[k] = f
    return [best[k] for k in sorted(best)]


def facts_as_of(
    store: PublishStore, as_of: str, *, issuer_key: str | None = None, field_id: str | None = None
) -> list[Fact]:
    from sqlalchemy import select

    from arp.storage.postgres_models import PublishedFactModel as M

    b = as_of_bound(as_of)
    q = select(M).where(M.valid_from <= b, M.valid_to.is_(None) | (M.valid_to > b))
    if issuer_key is not None:
        q = q.where(M.issuer_key == issuer_key)
    if field_id is not None:
        q = q.where(M.field_id == field_id)
    with store.session() as s:
        rows = [_fact_from_row(r) for r in s.scalars(q)]
    return visible(rows, as_of)  # one per key (highest version), sorted by key


def _events(store: PublishStore, *where, limit: int | None = None) -> list[FactEvent]:
    from sqlalchemy import select

    from arp.storage.postgres_models import FactEventModel as E

    q = select(E).where(*where).order_by(E.event_id)
    if limit is not None:
        q = q.limit(limit)
    with store.session() as s:
        return [FactEvent.model_validate({c.key: getattr(r, c.key) for c in E.__table__.columns}) for r in s.scalars(q)]


def events_since(store: PublishStore, after: str) -> list[FactEvent]:
    from arp.storage.postgres_models import FactEventModel as E

    return _events(store, E.at > after)


def read_events(store: PublishStore, *, after_id: int = 0, limit: int = 500) -> list[FactEvent]:
    from arp.storage.postgres_models import FactEventModel as E

    return _events(store, E.event_id > after_id, limit=limit)
