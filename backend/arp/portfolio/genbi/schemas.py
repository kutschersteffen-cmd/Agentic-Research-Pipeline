from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from arp.schemas.common import new_id, now_iso
from arp.schemas.portfolio import AggregationMetric, AggregationResult, PivotResult, TrendPoint

PanelKind = Literal["aggregation", "trend", "pivot"]
ChartHint = Literal["bar", "line", "table", "grid"]
FactKind = Literal[
    "total",
    "top_contributor",
    "concentration",
    "coverage",
    "unresolved",
    "trend_delta",
    "trend_mover",
    "largest_cell",
    "row_total",
    "news_flags",
]


class PanelSpec(BaseModel):
    """One panel of a generated dashboard: a single query against the
    deterministic engine plus how to draw it. Deliberately a thin wrapper
    over the primitives `AnalyticSpec`/`PivotSpec` already expose -- a
    panel adds a title, the sub-question it answers, and a chart hint, but
    never a new way to compute a number. That keeps the LLM's planning
    surface identical to what a user can build by hand in the Explore and
    Pivot tabs, so a generated panel is always reproducible as a manual
    query.
    """

    panel_id: str = Field(default_factory=lambda: new_id("pan"))
    title: str
    question: str = Field(default="", description="The sub-question this panel is meant to answer, in plain language.")
    kind: PanelKind = "aggregation"
    portfolio_filter: list[str] = Field(default_factory=list)
    security_filter: dict[str, str] = Field(default_factory=dict)
    group_by: str = Field(default="portfolio_id", description="Grouping dimension for kind=aggregation/trend.")
    row_dim: str = Field(default="", description="Row dimension for kind=pivot.")
    col_dim: str = Field(default="", description="Column dimension for kind=pivot.")
    metric: AggregationMetric = "market_value_sum"
    data_point_field_id: str | None = None
    as_of: str | None = Field(default=None, description="Snapshot date; None = latest available.")
    date_range: tuple[str, str] | None = Field(default=None, description="Required for kind=trend.")
    chart: ChartHint = "bar"


class DashboardSpec(BaseModel):
    """A saved, re-runnable dashboard definition. This -- not the prose --
    is the durable artifact: re-running the same spec against a later
    snapshot reproduces the same panels computed the same way, so a
    generated dashboard becomes a recurring report rather than a one-off
    prompt whose definition nobody can inspect afterwards.
    """

    dashboard_id: str = Field(default_factory=lambda: new_id("dash"))
    title: str
    brief: str = Field(default="", description="The plain-language request the planner turned into these panels.")
    goal: str = Field(default="", description="What the planner understood the dashboard should show.")
    panels: list[PanelSpec] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class DashboardFact(BaseModel):
    """One figure computed deterministically from a panel's result -- the
    only material the narrator is allowed to write prose about, and the
    reference set `narrator.check_grounding` checks generated text against.
    Every fact carries both a machine value and the exact rendering used in
    `text`, so "grounded" means "this number was actually computed", not
    "the model says it was".
    """

    fact_id: str = Field(default_factory=lambda: new_id("fact"))
    panel_id: str = ""
    kind: FactKind
    label: str
    value: float | None = None
    unit: str = ""
    text: str = Field(description="Deterministic rendering of the fact -- doubles as the narrator's fallback prose.")


class PanelResult(BaseModel):
    """A panel's executed result. Exactly one of `aggregation`/`trend`/
    `pivot` is populated, mirroring `PanelSpec.kind`. A panel that fails to
    execute (e.g. an unknown data-point field) carries `error` and is
    rendered as a failed panel -- one bad panel never discards the rest of
    the dashboard.
    """

    panel: PanelSpec
    as_of: str = ""
    aggregation: AggregationResult | None = None
    trend: list[TrendPoint] | None = None
    pivot: PivotResult | None = None
    facts: list[DashboardFact] = Field(default_factory=list)
    error: str = ""


class Narrative(BaseModel):
    """Generated prose plus its grounding verdict. `grounded=False` means a
    number or date appeared in the draft that no computed fact supports; in
    that case `text` is the deterministic fallback and the rejected draft is
    kept in `rejected_draft` so the failure is inspectable rather than
    invisible.
    """

    text: str = ""
    grounded: bool = True
    source: Literal["llm", "deterministic_fallback"] = "deterministic_fallback"
    ungrounded_tokens: list[str] = Field(default_factory=list)
    rejected_draft: str = ""


class GeneratedDashboard(BaseModel):
    """The full assembled result: the re-runnable spec, every panel's
    deterministically computed result and facts, and the narration layered
    on top. The prose is the last thing added and the only thing an LLM
    wrote -- strip it away and the dashboard still stands on its computed
    numbers.
    """

    spec: DashboardSpec
    generated_at: str = Field(default_factory=now_iso)
    as_of: str = ""
    panels: list[PanelResult] = Field(default_factory=list)
    headline: Narrative = Field(default_factory=Narrative)
    panel_narratives: dict[str, Narrative] = Field(default_factory=dict)
    warnings: list[str] = Field(
        default_factory=list,
        description="Planner panels rejected as invalid, panels that failed to execute, narration that failed grounding.",
    )
    clarification_needed: str = Field(
        default="", description="Set when the brief was too ambiguous to plan; no panels are invented in that case."
    )
