"""Bundles the small subset of Settings that RunStore's and
EngagementStore's best-effort Postgres-projection sync hooks need, so
those classes take one narrow, explicit config object instead of the
whole Settings -- same pattern as arp/ingestion/indexing_config.py's
IndexingConfig for the OpenSearch/object-store ingestion hooks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arp.config import Settings


@dataclass(frozen=True)
class ProjectionConfig:
    postgres_dsn: str | None = None
    company_records_projection_enabled: bool = False
    company_facts_projection_enabled: bool = False
    engagement_projection_enabled: bool = False

    @classmethod
    def from_settings(cls, settings: Settings) -> ProjectionConfig:
        return cls(
            postgres_dsn=settings.postgres_dsn,
            company_records_projection_enabled=settings.company_records_projection_enabled,
            company_facts_projection_enabled=settings.company_facts_projection_enabled,
            engagement_projection_enabled=settings.engagement_projection_enabled,
        )

    @property
    def company_records_enabled(self) -> bool:
        return bool(self.postgres_dsn and self.company_records_projection_enabled)

    @property
    def company_facts_enabled(self) -> bool:
        return bool(self.postgres_dsn and self.company_facts_projection_enabled)

    @property
    def engagement_enabled(self) -> bool:
        return bool(self.postgres_dsn and self.engagement_projection_enabled)
