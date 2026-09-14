"""Per-projector high-water marks, so `arp db reindex ...` rescans only
what is new.

`IndexCheckpointModel` (arp/storage/postgres_models.py) has documented
this since it was added, and `sync_all(..., since=)` /
`materialize_all(..., since=)` have accepted the parameter -- but nothing
ever read or wrote a checkpoint, and no reindex command offered the flag,
so every backfill was a full rescan of every run. This module is the
missing piece.

The mark is a manifest `updated_at` timestamp rather than a row count or
an offset, because that is what the projectors already filter on: a run
whose manifest has not been touched since the last backfill cannot have
new results.

Recorded *before* the sync it describes is read, never after: a run that
lands mid-backfill then shows up as "changed since" on the next pass
instead of being skipped forever. Re-projecting a run that was already
projected is a no-op in every projector (ON CONFLICT DO NOTHING for
records, an unchanged-value check for facts), so erring toward re-reading
costs nothing but time.
"""

from __future__ import annotations

from arp.storage.postgres import get_engine


def get_checkpoint(dsn: str, name: str) -> str | None:
    """The `updated_at` recorded by the last backfill of this projector, or
    None if it has never run (meaning: rescan everything)."""
    from sqlalchemy.orm import Session

    from arp.storage.postgres_models import IndexCheckpointModel

    with Session(get_engine(dsn)) as session:
        row = session.get(IndexCheckpointModel, name)
        return None if row is None else row.last_synced_at


def set_checkpoint(dsn: str, name: str, last_synced_at: str) -> None:
    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy.orm import Session

    from arp.storage.postgres_models import IndexCheckpointModel

    with Session(get_engine(dsn)) as session:
        stmt = insert(IndexCheckpointModel).values(name=name, last_synced_at=last_synced_at)
        stmt = stmt.on_conflict_do_update(index_elements=["name"], set_={"last_synced_at": stmt.excluded.last_synced_at})
        session.execute(stmt)
        session.commit()
