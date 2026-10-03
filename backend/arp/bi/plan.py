from __future__ import annotations

from pydantic import BaseModel


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
    time_range: str | None = None


class ChartPlan(BaseModel):
    title: str
    goal: str = ""
    charts: list[ChartSpec]  # 1..MAX_CHARTS, enforced by the validator
