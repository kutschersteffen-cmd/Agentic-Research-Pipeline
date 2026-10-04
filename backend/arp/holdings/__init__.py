from __future__ import annotations

from arp.schemas.portfolio import Holding


def load(store, kind: str, holder_id: str, as_of: str) -> list[Holding]:
    """The working snapshot of the newest date on or before `as_of`: a month with no data reads the one before."""
    dates = [d for d in store.list_snapshot_dates(holder_id, kind=kind) if d <= as_of]
    return store.load_snapshot(holder_id, dates[-1], kind=kind) if dates else []
