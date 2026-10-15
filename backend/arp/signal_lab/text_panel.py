from __future__ import annotations

from arp.signal_lab.text_store import TextRecord


def manifest_from_text_items(items: list[TextRecord]) -> list[dict]:
    """The manifest `arp replicate score-sentiment` reads. ticker is the issuer key; the month is the
    event time's UTC month (event_time is canonical, so its first 7 chars are the month)."""
    return [
        {
            "ticker": i.company_id,
            "period_end": f"{i.event_time[:7]}-01",
            "published_at": i.event_time,
            "doc_id": i.item_id,
            "text": f"{i.title}\n\n{i.body}",
        }
        for i in items
        if i.company_id
    ]
