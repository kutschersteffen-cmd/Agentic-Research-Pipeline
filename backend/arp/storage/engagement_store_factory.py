"""Single choke point for building the engagement store (API, CLI and monthly run all call this)."""

from __future__ import annotations

from arp.config import Settings
from arp.db.session import require_dsn
from arp.storage.engagement_store import EngagementStore
from arp.storage.postgres_engagement_store import PostgresEngagementStore


def build_engagement_store(settings: Settings) -> EngagementStore | PostgresEngagementStore:
    if settings.engagement_store == "postgres":
        return PostgresEngagementStore(require_dsn(settings))
    return EngagementStore(settings.engagements_dir)
