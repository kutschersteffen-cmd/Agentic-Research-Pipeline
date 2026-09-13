from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from arp.llm.base import LLMClient, LLMUsage
from arp.portfolio.aggregation import DIMENSIONS
from arp.portfolio.genbi.schemas import DashboardSpec, PanelSpec
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import DataPointSchema
from arp.schemas.portfolio import AnalyticSpec, Portfolio

MAX_PANELS = 6
"""Cap on panels per dashboard. A generative BI layer that answers a vague
brief with twelve panels is padding, not analysis; the planner is told to
pick the few that matter and anything past this is truncated with a visible
warning rather than quietly executed."""

MAX_EXAMPLES = 6
"""Cap on worked examples in the planning prompt. Examples are the cheapest
accuracy lever available (they are what a saved dashboard already is), but
they compete with the directories for the model's attention -- six recent,
human-kept plans is enough to convey house style without burying the data
the planner actually has to choose from."""

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


_REPAIR_SYSTEM_PROMPT = """\
You are fixing panels from a dashboard plan you just produced. Each one was
rejected by a validator that checked it against the data that actually
exists, and you are given the exact reason for each rejection.

Return one replacement per rejected panel, in the same order, keeping each
panel's original title so it can be matched back. Fix only what the
rejection reason names -- keep the sub-question the panel was asking. A
rejection means the value you used does not exist, so replace it with the
nearest one that does (from the directories below), never with a guess of
the same kind.

If a rejected panel cannot be expressed at all with the available
dimensions, metrics and fields, leave it out of your response rather than
returning something that answers a different question -- it will simply be
dropped, which is the correct outcome.
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


class _RepairedPanels(BaseModel):
    panels: list[_PlannedPanel] = Field(default_factory=list)


class PlannerExample(BaseModel):
    """One brief -> panels pair an analyst actually kept. Few-shot material
    for the planner, drawn only from specs a human deliberately saved (a
    saved dashboard, a saved analytic) -- never from a generated plan
    nobody chose to keep, which would let the planner reinforce its own
    unreviewed habits."""

    brief: str
    panels: list[PanelSpec] = Field(default_factory=list)


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
    examples: list[PlannerExample] = Field(
        default_factory=list, description="Human-kept brief -> panels pairs, re-validated against the directories above."
    )


def build_context(
    portfolios: list[Portfolio],
    companies: list[CompanyRef],
    securities_asset_classes: list[str],
    snapshot_dates: list[str],
    schema: DataPointSchema | None,
    saved_dashboards: list[DashboardSpec] | None = None,
    saved_analytics: list[AnalyticSpec] | None = None,
) -> PlannerContext:
    """Assembles everything the planner may reference. Saved dashboards and
    analytics become worked examples, but only after being re-validated
    against the directories built here: a saved plan naming a portfolio or
    field that has since been renamed would otherwise teach the planner an
    identifier that no longer exists.
    """
    ctx = PlannerContext(
        portfolios=portfolios,
        companies=companies,
        sectors=sorted({c.sector for c in companies if c.sector}),
        asset_classes=sorted(set(securities_asset_classes)),
        snapshot_dates=snapshot_dates,
        data_point_fields=[(f.field_id, f"{f.name} ({f.unit or f.data_type})") for f in (schema.fields if schema else [])],
    )
    ctx.examples = _build_examples(saved_dashboards or [], saved_analytics or [], ctx)
    return ctx


def _panel_from_analytic(spec: AnalyticSpec) -> PanelSpec:
    """A saved analytic is a one-panel dashboard -- same primitives, so it
    makes the same kind of example (and usually a question-shaped one,
    since `qa_agent.py` names analytics after the question asked)."""
    return PanelSpec(
        title=spec.name,
        kind="trend" if spec.date_range else "aggregation",
        portfolio_filter=spec.portfolio_filter,
        security_filter=spec.security_filter,
        group_by=spec.group_by,
        metric=spec.metric,
        data_point_field_id=spec.data_point_field_id,
        date_range=spec.date_range,
        chart="line" if spec.date_range else "bar",
    )


def _still_valid(panel: PanelSpec, ctx: PlannerContext) -> bool:
    """Re-runs the panel through the same validator a freshly planned panel
    faces. Silent on failure by design: a stale example is not the
    analyst's request and its rejection is not something they need told --
    it is simply not shown to the planner."""
    validated, _warning = _validate(_planned_from_spec(panel), ctx)
    return validated is not None


def _build_examples(
    dashboards: list[DashboardSpec], analytics: list[AnalyticSpec], ctx: PlannerContext
) -> list[PlannerExample]:
    candidates: list[PlannerExample] = []
    for spec in sorted(dashboards, key=lambda d: d.created_at, reverse=True):
        if spec.brief.strip():
            candidates.append(PlannerExample(brief=spec.brief, panels=list(spec.panels)))
    for spec in sorted(analytics, key=lambda a: a.created_at, reverse=True):
        if spec.name.strip():
            candidates.append(PlannerExample(brief=spec.name, panels=[_panel_from_analytic(spec)]))

    examples: list[PlannerExample] = []
    seen_briefs: set[str] = set()
    for candidate in candidates:
        key = candidate.brief.strip().lower()
        if key in seen_briefs:
            continue
        current = [p for p in candidate.panels if _still_valid(p, ctx)]
        if not current:
            continue
        seen_briefs.add(key)
        examples.append(PlannerExample(brief=candidate.brief, panels=current))
        if len(examples) == MAX_EXAMPLES:
            break
    return examples


def _summarize_panel(panel: PanelSpec) -> str:
    dims = f"{panel.row_dim} x {panel.col_dim}" if panel.kind == "pivot" else panel.group_by
    parts = [panel.title, panel.kind, f"by {dims}", panel.metric]
    if panel.data_point_field_id:
        parts.append(f"field={panel.data_point_field_id}")
    if panel.security_filter:
        parts.append(f"filter={panel.security_filter}")
    if panel.portfolio_filter:
        parts.append(f"portfolios={', '.join(panel.portfolio_filter)}")
    if panel.date_range:
        parts.append(f"range={panel.date_range[0]}..{panel.date_range[1]}")
    return " | ".join(parts)


def _render_examples(examples: list[PlannerExample]) -> str:
    if not examples:
        return ""
    lines = [
        "",
        "Worked examples -- dashboards and analytics this deployment's own",
        "analysts chose to keep. Match their level of aggregation and their",
        "naming; do not reuse their panels when the brief asks something else.",
    ]
    for i, example in enumerate(examples, start=1):
        lines.append(f'Example {i} -- brief: "{example.brief}"')
        lines += [f"  - {_summarize_panel(p)}" for p in example.panels]
    return "\n".join(lines)


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
    return "\n".join(lines) + _render_examples(ctx.examples)


def _planned_from_spec(panel: PanelSpec) -> _PlannedPanel:
    """Turns a stored panel back into the planner's own output shape, so a
    saved example faces exactly the validator a fresh plan does rather than
    a second, drifting copy of those rules."""
    return _PlannedPanel(
        title=panel.title,
        question=panel.question,
        kind=panel.kind,
        portfolio_filter=list(panel.portfolio_filter),
        security_filter=dict(panel.security_filter),
        group_by=panel.group_by,
        row_dim=panel.row_dim,
        col_dim=panel.col_dim,
        metric=panel.metric,
        data_point_field_id=panel.data_point_field_id,
        as_of=panel.as_of,
        date_range=list(panel.date_range) if panel.date_range else None,
        chart=panel.chart,
    )


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


async def _repair_panels(
    brief: str,
    llm: LLMClient,
    ctx: PlannerContext,
    rejected: list[tuple[int, _PlannedPanel, str]],
    slots: list[PanelSpec | None],
) -> tuple[list[str], LLMUsage]:
    """One bounded repair attempt at the panels the validator rejected.

    Exactly one round, never recursive: the rejection reasons go back to the
    planner, it returns replacements, and those face the same validator. A
    replacement that validates fills its original slot (so panel order
    survives the repair); one that doesn't leaves the panel dropped. Either
    way both attempts are reported, because a repaired panel is still a
    panel the analyst didn't ask for by name and should be able to audit.
    """
    listing = "\n\n".join(
        f"{order}. Rejected panel {candidate.title!r}\n"
        f"   plan: {candidate.model_dump_json()}\n"
        f"   rejection reason: {reason}"
        for order, (_idx, candidate, reason) in enumerate(rejected, start=1)
    )
    prompt = (
        f"Available data:\n{_render_context(ctx)}\n\nOriginal brief: {brief}\n\n"
        f"Panels to fix ({len(rejected)}):\n{listing}"
    )
    repaired, usage = await llm.complete_structured(
        system=_REPAIR_SYSTEM_PROMPT, prompt=prompt, output_model=_RepairedPanels
    )

    # Match by title first (the repair prompt asks for titles to be kept),
    # falling back to the order the panels were listed in. Each replacement
    # is consumed once: two rejected panels sharing a title must not both
    # resolve to the same replacement and land it in two slots.
    by_title: dict[str, list[_PlannedPanel]] = {}
    for panel in repaired.panels:
        by_title.setdefault(panel.title, []).append(panel)
    unclaimed = list(repaired.panels)

    warnings: list[str] = []
    for idx, candidate, reason in rejected:
        queue = by_title.get(candidate.title) or []
        replacement = queue.pop(0) if queue else (unclaimed[0] if unclaimed else None)
        if replacement is not None and replacement in unclaimed:
            unclaimed.remove(replacement)
        if replacement is None:
            warnings.append(f"{reason} Re-plan returned no replacement; panel dropped.")
            continue
        panel, retry_warning = _validate(replacement, ctx)
        if panel is None:
            warnings.append(f"{reason} Re-planned once and still invalid ({retry_warning.split(': dropped -- ', 1)[-1]}); panel dropped.")
            continue
        slots[idx] = panel
        warnings.append(f"{reason} Re-planned on retry as: {_summarize_panel(panel)}.")
    return warnings, usage


async def plan_dashboard(
    brief: str, llm: LLMClient, ctx: PlannerContext, *, repair: bool = True
) -> tuple[DashboardSpec | None, str, list[str], LLMUsage]:
    """Turns a brief into a validated, re-runnable `DashboardSpec`.

    Returns `(spec, clarification_needed, warnings, usage)`. The LLM's only
    output is the query plan -- what to look at, never what the answer is.
    Every planned panel is re-validated against the live directories before
    it can execute; a rejected panel gets exactly one bounded re-plan
    attempt (`repair`), and both attempts appear in `warnings` either way,
    so the analyst sees what the planner tried, why it was rejected, and
    what replaced it.
    """
    prompt = f"Available data:\n{_render_context(ctx)}\n\nBrief: {brief}"
    planned, usage = await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=_PlannedDashboard)
    total_usage = LLMUsage(
        input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, model=usage.model, prompt_version=usage.prompt_version
    )

    if not planned.understood:
        return None, planned.clarification_needed or "The brief could not be mapped onto the available data.", [], total_usage

    slots: list[PanelSpec | None] = []
    rejected: list[tuple[int, _PlannedPanel, str]] = []
    for index, candidate in enumerate(planned.panels):
        panel, warning = _validate(candidate, ctx)
        slots.append(panel)
        if panel is None:
            rejected.append((index, candidate, warning))

    if rejected and repair:
        warnings, repair_usage = await _repair_panels(brief, llm, ctx, rejected, slots)
        total_usage.input_tokens += repair_usage.input_tokens
        total_usage.output_tokens += repair_usage.output_tokens
    else:
        warnings = [reason for _index, _candidate, reason in rejected]

    panels = [panel for panel in slots if panel is not None]
    if len(panels) > MAX_PANELS:
        warnings.append(f"Planner proposed {len(panels)} panels; kept the first {MAX_PANELS}.")
        panels = panels[:MAX_PANELS]

    if not panels:
        return None, "No valid panel could be planned from this brief.", warnings, total_usage

    spec = DashboardSpec(title=planned.title or brief[:80], brief=brief, goal=planned.goal, panels=panels)
    return spec, "", warnings, total_usage
