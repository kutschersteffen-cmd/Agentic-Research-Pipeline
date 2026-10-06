"""Load records (holdings, ESG and security master files), kept in the append-only event log as `load_recorded` events."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from arp.schemas.common import now_iso


class LoadRecord(BaseModel):
    kind: Literal["holdings", "esg", "security_master", "news"]
    source_id: str
    month: str
    status: Literal["ok", "failed"]
    content_hash: str
    detail: str = ""
    at: str = ""


def record_load(store, rec: LoadRecord) -> None:
    payload = rec.model_dump()
    payload["at"] = rec.at or now_iso()
    store.append_governance_event("load_recorded", payload)


def latest_load(store, kind: str, source_id: str, month: str) -> LoadRecord | None:
    hits = [
        e for e in store.list_governance_events()
        if e.get("event_type") == "load_recorded" and (e["kind"], e["source_id"], e["month"]) == (kind, source_id, month)
    ]
    return LoadRecord.model_validate({k: v for k, v in hits[-1].items() if k != "event_type"}) if hits else None
