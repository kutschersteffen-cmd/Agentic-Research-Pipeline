from __future__ import annotations

from pydantic import BaseModel, field_validator


class DatasetMeta(BaseModel):
    columns: set[str]
    metrics: set[str]


MAX_CHARTS = 6


class ChartSpec(BaseModel):
    title: str
    question: str = ""
    viz_type: str
    dataset: str
    metrics: list[str]  # saved-metric names from DatasetMeta.metrics
    groupby: list[str] = []
    filters: dict[str, str] = {}  # column -> value


class NativeFilter(BaseModel):
    """A dashboard select filter on `dataset.column`."""

    name: str
    dataset: str
    column: str


class ChartPlan(BaseModel):
    title: str
    goal: str = ""
    charts: list[ChartSpec]  # 1..MAX_CHARTS, enforced by the validator


class DashboardTemplate(BaseModel):
    """A committed dashboard (arp/bi/templates/*.json) that `arp bi bootstrap` provisions."""

    slug: str
    title: str
    goal: str = ""
    charts: list[ChartSpec]
    native_filters: list[NativeFilter] = []

    @field_validator("slug")
    @classmethod
    def _arp_slug(cls, slug: str) -> str:
        # ARP only embeds and rebuilds arp- dashboards (service.embed_token).
        if not slug.startswith("arp-"):
            raise ValueError(f"template slug {slug!r} must start with 'arp-'")
        return slug
