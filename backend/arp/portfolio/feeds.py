"""Data Hub's feed overview: one row per input feed with its last load and whether it is behind. Read-only; it only
reads what the loads already record (`load_recorded` events, holder configs, the identifier map, stored news)."""

from __future__ import annotations

from datetime import date

from arp.holdings import security_master
from arp.holdings.intake import holder_status, previous_month_end
from arp.portfolio.loads import LoadRecord
from arp.storage.identifier_map import IdentifierMapStore


def _latest_loads(store) -> dict[tuple[str, str], LoadRecord]:
    """The last load attempt per (kind, source), over all months."""
    out: dict[tuple[str, str], LoadRecord] = {}
    for e in store.list_governance_events():
        if e.get("event_type") == "load_recorded":
            out[(e["kind"], e["source_id"])] = LoadRecord.model_validate({k: v for k, v in e.items() if k != "event_type"})
    return out


def overview(store, idmap: IdentifierMapStore, today: date) -> list[dict]:
    loads = _latest_loads(store)
    expected_month = previous_month_end(today)[:7]
    rows = []

    master = security_master.status(store, idmap)
    rows.append({
        "feed": "security_master", "source_id": "file", "channel": "file", "as_of": None,
        "last_load": loads.get(("security_master", "file")),
        "stale": master["issuers"] == 0,
        "detail": f"{master['issuers']} issuers" if master["issuers"] else "not loaded: every holding is unmatched",
    })
    for h in holder_status(store, today):
        rows.append({
            "feed": "index" if h["kind"] == "index" else "holdings", "source_id": h["holder_id"], "channel": h["source"],
            "as_of": h["as_of"], "last_load": loads.get(("holdings", h["holder_id"])), "stale": h["stale"],
            "detail": h["last_error"] or (f"expected {h['expected_as_of']}" if h["stale"] else ""),
        })
    # ESG sources, and holdings sources with loads but no holder config (e.g. seeded data): judged by their last ok month.
    configured = {h.holder_id for h in store.list_holders()}
    events = [e for e in store.list_governance_events() if e.get("event_type") == "load_recorded" and e["status"] == "ok"]
    for (kind, source), rec in loads.items():
        if kind == "esg" or (kind == "holdings" and source not in configured):
            ok_month = max((e["month"] for e in events if (e["kind"], e["source_id"]) == (kind, source)), default=None)
            behind = ok_month is None or ok_month < expected_month
            rows.append({
                "feed": kind, "source_id": source, "channel": None, "as_of": ok_month, "last_load": rec, "stale": behind,
                "detail": f"expected {expected_month}" if behind else "",
            })
    news = store.list_news()
    latest = max((n.published_at for n in news), default=None)
    rows.append({
        "feed": "news", "source_id": "default", "channel": "api", "as_of": latest[:10] if latest else None,
        "last_load": loads.get(("news", "default")), "stale": latest is None,
        "detail": f"{len(news)} items stored" if news else "no news stored",
    })
    return [{**r, "last_load": r["last_load"].model_dump() if r["last_load"] else None} for r in rows]
