"""LLM planner: turns a plain-language brief into a validated ChartPlan.
The prompt is built from the catalog (schema and descriptions only, never
row data); the validator is the gate, with exactly one repair round."""

from __future__ import annotations

from pydantic import BaseModel

from arp.bi.catalog import MAX_GROUPBY, MIN_GROUPBY, TEMPORAL_COLUMNS, VIEW_DATASETS, VIZ_ALLOWLIST
from arp.bi.plan import MAX_CHARTS, ChartPlan, DatasetMeta
from arp.bi.validator import validate_plan
from arp.llm.base import LLMClient


class PlannerRefusal(BaseModel):
    """What the model returns: a plan, or a clarification when the brief
    cannot be answered from the listed datasets (the portfolio planner's
    `clarification_needed` pattern)."""

    plan: ChartPlan | None = None
    clarification_needed: str = ""


def _shape_rule(viz: str) -> str:
    lo, hi = MIN_GROUPBY.get(viz, 0), MAX_GROUPBY.get(viz)
    if hi == 0:
        rule = "no groupby columns"
    elif lo:
        rule = f"at least {lo} groupby column(s)"
    else:
        rule = "groupby optional"
    if viz == "echarts_timeseries_line":
        rule += "; the first groupby column must be a date column of the dataset"
    return f"- {viz}: {rule}"


def _build_system(metas: dict[str, DatasetMeta]) -> str:
    datasets = []
    for name, d in VIEW_DATASETS.items():
        if name not in metas:
            continue
        cols = "\n".join(
            f"    - {c}: {desc}" + (" [date]" if c in TEMPORAL_COLUMNS[name] else "")
            for c, desc in d.columns.items()
            if c in metas[name].columns
        )
        mets = "\n".join(f"    - {m.name}: {m.description}" for m in d.metrics if m.name in metas[name].metrics)
        datasets.append(f"  {name}: {d.description}\n  columns:\n{cols}\n  metrics:\n{mets}")
    return f"""\
You are the planning half of a BI dashboard designer. Given an analyst's
plain-language brief, you design a small set of charts, each ONE query
against a curated dataset. You never compute or state a number and you never
write SQL; a separate step turns your plan into real charts.

Choose only from the datasets, metrics, columns and chart types listed
below. Never invent a dataset, column or metric; metrics are referenced by
their exact name. Filters are column -> exact value. A plan has between 1
and {MAX_CHARTS} charts with unique titles, each answering a distinct
sub-question.

The facts datasets are reviewed-only: company_facts holds only
approved facts. Use company_facts_pending ONLY when the brief asks about the
review backlog or pending items; never use it to answer ordinary questions.

If the brief cannot be answered from these datasets, do not guess: leave
plan empty and put what is missing or ambiguous in clarification_needed.

Datasets:
{chr(10).join(datasets)}

Chart types (viz_type) and their groupby shape:
{chr(10).join(_shape_rule(v) for v in VIZ_ALLOWLIST)}
"""


async def plan_from_brief(
    brief: str, metas: dict[str, DatasetMeta], llm: LLMClient
) -> tuple[ChartPlan | None, list[str]]:
    system = _build_system(metas)
    out, _ = await llm.complete_structured(system=system, prompt=f"Brief: {brief}", output_model=PlannerRefusal)
    if out.plan is None:
        return None, [out.clarification_needed or "The brief could not be mapped onto the available datasets."]
    errors = validate_plan(out.plan, metas)
    if not errors:
        return out.plan, []

    repair = (
        f"Brief: {brief}\n\nYour previous plan failed validation:\n"
        + "\n".join(f"- {e}" for e in errors)
        + "\n\nReturn a corrected plan, or a clarification if the brief cannot be answered."
    )
    out, _ = await llm.complete_structured(system=system, prompt=repair, output_model=PlannerRefusal)
    if out.plan is None:
        return None, [out.clarification_needed or "The brief could not be mapped onto the available datasets."]
    errors = validate_plan(out.plan, metas)
    return (None, errors) if errors else (out.plan, [])
