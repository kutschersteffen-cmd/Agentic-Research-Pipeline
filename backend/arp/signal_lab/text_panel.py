from __future__ import annotations

from arp.signal_lab.text_store import TextRecord
from arp.signal_lab.times import month_end_time


def manifest_from_text_items(items: list[TextRecord]) -> list[dict]:
    """The manifest `arp replicate score-sentiment` reads. ticker is the issuer key; the month is the
    event time's UTC month, the calendar month-end grid the adapters and prices use."""
    return [
        {
            "ticker": i.company_id,
            "period_end": month_end_time(i.event_time[:10])[:10],
            "published_at": i.event_time,
            "doc_id": i.item_id,
            "text": f"{i.title}\n\n{i.body}",
        }
        for i in items
        if i.company_id
    ]
