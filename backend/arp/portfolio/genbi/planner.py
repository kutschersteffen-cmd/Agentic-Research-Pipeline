from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from arp.llm.base import LLMClient, LLMUsage
from arp.portfolio.aggregation import DIMENSIONS
from arp.portfolio.genbi.schemas import DashboardSpec, PanelSpec
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import DataPointSchema
from arp.schemas.portfolio import Portfolio

MAX_PANELS = 6
"""Cap on panels per dashboard. A generative BI layer that answers a vague
brief with twelve panels is padding, not analysis; the planner is told to
pick the few that matter and anything past this is truncated with a visible
warning rather than quietly executed."""

_VALID_METRICS = ("market_value_sum", "weighted_avg_datapoint", "count")

_SYSTEM_PROMPT = f"""\
You are the planning half of a generative BI tool for portfolio risk
monitoring. Given an analyst's plain-language brief, you design a small
dashboard: a set of panels, each of which is ONE query against a
deterministic holdings aggregation engine.

You never compute, estimate, or state a number. You do not write any
commentary about results -- you have not seen any results. Your entire
output is the query plan; another, separate step executes it and a third
step narrates the real computed figures.

Each panel has:
- kind: "aggregation" (one snapshot, grouped), "trend" (the same grouped
  query repeated across every snapshot in date_range), or "pivot" (two
  dimensions crossed in a grid).
- group_by (aggregation/trend) or row_dim + col_dim (pivot), each one of:
  {", ".join(DIMENSIONS)}.
- metric: "market_value_sum" (EUR exposure), "weighted_avg_datapoint"
  (value-weighted average of a data-point field -- requires
  data_point_field_id), or "count" (number of holdings).
- security_filter: dimension -> exact value, e.g. {{"asset_class": "equity"}}.
  Only the dimensions listed above are filterable, and the value must be an
  exact match on that dimension (a company_id from the directory, an asset
  class, a sector spelled as the directory spells it).
- portfolio_filter: portfolio_ids to restrict to; empty means all.
- date_range: [start, end] -- required for kind="trend", omit otherwise.
- chart: "bar" for a grouped comparison, "line" for a trend, "grid" for a
  pivot, "table" when the rows matter more than the shape.

Design guidance: at most {MAX_PANELS} panels, each answering a distinct
sub-question, ordered so the broadest framing comes first. Prefer a mix of
levels (overall exposure, a breakdown, a trend, a concentration or data-
quality view) over several near-identical breakdowns. Give every panel a
short title and state the sub-question it answers. When the brief concerns
climate or emissions, use weighted_avg_datapoint with the relevant climate
field rather than inventing a metric.

If the brief is too vague or names something outside the available
portfolios, dimensions, and fields, set understood=false and say what you
need in clarification_needed instead of guessing a dashboard.
"""


class _PlannedPanel(BaseModel):
    title: str
    question: str = ""
    kind: Literal["aggregation", "trend", "pivot"] = "aggregation"
    portfolio_filter: list[str] = Field(default_factory=list)
    security_filter: dict[str, str] = Field(default_factory=dict)
    group_by: str = "portfolio_id"
    row_dim: str = ""
    col_dim: str = ""
    metric: str = "market_value_sum"
    data_point_field_id: str | None = None
    as_of: str | None = None
    date_range: list[str] | None = None
    chart: Literal["bar", "line", "table", "grid"] = "bar"


class _PlannedDashboard(BaseModel):
    understood: bool = True
    clarification_needed: str = ""
    title: str = ""
    goal: str = ""
    panels: list[_PlannedPanel] = Field(default_factory=list)


class PlannerContext(BaseModel):
    """Everything the planner is allowed to reference. Assembled from the
    live store, so a planned panel can only name a portfolio, company,
    sector, field, or snapshot date that actually exists -- the validation
    below then re-checks it, because a prompt is guidance and the check is
    the control."""

    portfolios: list[Portfolio] = Field(default_factory=list)
    companies: list[CompanyRef] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    asset_classes: list[str] = Field(default_factory=list)
    snapshot_dates: list[str] = Field(default_factory=list)
    data_point_fields: list[tuple[str, str]] = Field(
        default_factory=list, description="(field_id, human name/unit) pairs the planner may aggregate."
    )


def build_context(
    portfolios: list[Portfolio],
    companies: list[CompanyRef],
    securities_asset_classes: list[str],
    snapshot_dates: list[str],
    schema: DataPointSchema | None,
) -> PlannerContext:
    return PlannerContext(
        portfolios=portfolios,
        companies=companies,
        sectors=sorted({c.sector for c in companies if c.sector}),
        asset_classes=sorted(set(securities_asset_classes)),
        snapshot_dates=snapshot_dates,
        data_point_fields=[(f.field_id, f"{f.name} ({f.unit or f.data_type})") for f in (schema.fields if schema else [])],
    )


def _render_context(ctx: PlannerContext) -> str:
    lines = ["Portfolios (portfolio_id: name [tags]):"]
    lines += [f"  {p.portfolio_id}: {p.name} [{', '.join(p.tags)}]" for p in ctx.portfolios] or ["  (none)"]
    lines.append("Issuers (company_id: name -- sector, country):")
    lines += [f"  {c.company_id}: {c.name} -- {c.sector or 'n/a'}, {c.country or 'n/a'}" for c in ctx.companies] or ["  (none)"]
    lines.append(f"Sectors: {', '.join(ctx.sectors) or '(none)'}")
    lines.append(f"Asset classes: {', '.join(ctx.asset_classes) or '(none)'}")
    lines.append(f"Snapshot dates available: {', '.join(ctx.snapshot_dates) or '(none)'}")
    lines.append("Data-point fields (field_id: name):")
    lines += [f"  {fid}: {name}" for fid, name in ctx.data_point_fields] or ["  (none)"]
    return "\n".join(lines)


def _validate(planned: _PlannedPanel, ctx: PlannerContext) -> tuple[PanelSpec | None, str]:
    """Re-checks a planned panel against what really exists. A panel that
    references an unknown dimension, metric, field, or portfolio is dropped
    with a warning rather than silently coerced to something valid: a
    coerced panel would answer a question nobody asked while looking like
    it answered the one they did.
    """
    where = f"panel {planned.title!r}"
    field_ids = {fid for fid, _name in ctx.data_point_fields}
    portfolio_ids = {p.portfolio_id for p in ctx.portfolios}

    if planned.metric not in _VALID_METRICS:
        return None, f"{where}: dropped -- unknown metric {planned.metric!r}."
    if planned.metric == "weighted_avg_datapoint" and planned.data_point_field_id not in field_ids:
        return None, f"{where}: dropped -- unknown data-point field {planned.data_point_field_id!r}."
    unknown_portfolios = [p for p in planned.portfolio_filter if p not in portfolio_ids]
    if unknown_portfolios:
        return None, f"{where}: dropped -- unknown portfolio_id(s) {', '.join(unknown_portfolios)}."
    unknown_filter_dims = [d for d in planned.security_filter if d not in DIMENSIONS]
    if unknown_filter_dims:
        return None, f"{where}: dropped -- unknown filter dimension(s) {', '.join(unknown_filter_dims)}."

    # A misspelled filter value is worse than an error: the panel runs, finds
    # nothing, and reports "no exposure" for something the portfolio may well
    # hold. Checked against the live directories wherever one exists.
    known_values = {
        "company_id": {c.company_id for c in ctx.companies},
        "company_name": {c.name for c in ctx.companies},
        "sector": set(ctx.sectors),
        "country": {c.country for c in ctx.companies if c.country},
        "asset_class": set(ctx.asset_classes),
        "portfolio_id": portfolio_ids,
    }
    for dimension, value in planned.security_filter.items():
        valid = known_values.get(dimension)
        if valid and value not in valid:
            return None, f"{where}: dropped -- filter {dimension}={value!r} matches nothing in the {dimension} directory."

    if planned.kind == "pivot":
        if planned.row_dim not in DIMENSIONS or planned.col_dim not in DIMENSIONS:
            return None, f"{where}: dropped -- pivot needs two known dimensions, got {planned.row_dim!r} x {planned.col_dim!r}."
        if planned.row_dim == planned.col_dim:
            return None, f"{where}: dropped -- a pivot of {planned.row_dim!r} against itself adds nothing."
    else:
        if planned.group_by not in DIMENSIONS:
            return None, f"{where}: dropped -- unknown group_by {planned.group_by!r}."

    date_range: tuple[str, str] | None = None
    if planned.kind == "trend":
        if not planned.date_range or len(planned.date_range) != 2:
            if len(ctx.snapshot_dates) < 2:
                return None, f"{where}: dropped -- a trend needs a date range and fewer than two snapshots exist."
            date_range = (ctx.snapshot_dates[0], ctx.snapshot_dates[-1])
        else:
            start, end = planned.date_range[0], planned.date_range[1]
            if start > end:
                start, end = end, start
            date_range = (start, end)
    elif planned.date_range:
        return None, f"{where}: dropped -- date_range is only valid for kind='trend'."

    if planned.as_of and ctx.snapshot_dates and planned.as_of not in ctx.snapshot_dates:
        return None, f"{where}: dropped -- as_of {planned.as_of} is not an available snapshot date."

    chart = planned.chart
    if planned.kind == "trend" and chart == "bar":
        chart = "line"
    if planned.kind == "pivot" and chart in ("bar", "line"):
        chart = "grid"

    return (
        PanelSpec(
            title=planned.title or planned.question or "Untitled panel",
            question=planned.question,
            kind=planned.kind,
            portfolio_filter=planned.portfolio_filter,
            security_filter=planned.security_filter,
            group_by=planned.group_by,
            row_dim=planned.row_dim,
            col_dim=planned.col_dim,
            metric=planned.metric,  # type: ignore[arg-type]
            data_point_field_id=planned.data_point_field_id if planned.metric == "weighted_avg_datapoint" else None,
            as_of=planned.as_of,
            date_range=date_range,
            chart=chart,
        ),
        "",
    )


async def plan_dashboard(
    brief: str, llm: LLMClient, ctx: PlannerContext
) -> tuple[DashboardSpec | None, str, list[str], LLMUsage]:
    """Turns a brief into a validated, re-runnable `DashboardSpec`.

    Returns `(spec, clarification_needed, warnings, usage)`. The LLM's only
    output is the query plan -- what to look at, never what the answer is.
    Every planned panel is re-validated against the live directories before
    it can execute, and rejected panels surface as warnings on the
    dashboard so the analyst sees what the planner tried and why it
    didn't run.
    """
    prompt = f"Available data:\n{_render_context(ctx)}\n\nBrief: {brief}"
    planned, usage = await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=_PlannedDashboard)

    if not planned.understood:
        return None, planned.clarification_needed or "The brief could not be mapped onto the available data.", [], usage

    warnings: list[str] = []
    panels: list[PanelSpec] = []
    for candidate in planned.panels:
        panel, warning = _validate(candidate, ctx)
        if panel is None:
            warnings.append(warning)
            continue
        panels.append(panel)

    if len(panels) > MAX_PANELS:
        warnings.append(f"Planner proposed {len(panels)} panels; kept the first {MAX_PANELS}.")
        panels = panels[:MAX_PANELS]

    if not panels:
        return None, "No valid panel could be planned from this brief.", warnings, usage

    spec = DashboardSpec(title=planned.title or brief[:80], brief=brief, goal=planned.goal, panels=panels)
    return spec, "", warnings, usage
