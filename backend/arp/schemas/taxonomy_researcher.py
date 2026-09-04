from __future__ import annotations

from pydantic import BaseModel, Field


class TaxonomyResearcherScheduleConfig(BaseModel):
    """Persisted to <taxonomy_researcher_state_dir>/schedule.json -- same
    shape/role as arp.schemas.discovery.DiscoveryScheduleConfig."""

    enabled: bool = False
    interval_hours: float = 168.0  # weekly -- taxonomies don't need daily rescanning
    taxonomy_ids: list[str] | None = Field(
        default=None, description="Scan only these taxonomy_ids. None means every ratified taxonomy in the library."
    )
    last_run_id: str | None = None


class TaxonomyResearchFinding(BaseModel):
    """One ratified taxonomy's research-pass outcome -- proposed=True means
    a new DRAFT version was written (never auto-ratified; a human still
    reviews and calls POST /api/taxonomies/{id}/ratify separately).
    """

    taxonomy_id: str
    taxonomy_name: str
    proposed: bool
    new_version: int | None = None
    added_activity_names: list[str] = Field(default_factory=list)
    reason: str = Field(default="", description="Why proposed=False, or a summary of what changed when True.")
