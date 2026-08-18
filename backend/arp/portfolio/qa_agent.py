from __future__ import annotations

from pydantic import BaseModel, Field

from arp.llm.base import LLMClient, LLMUsage
from arp.portfolio import analytics
from arp.portfolio.aggregation import DIMENSIONS
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import AggregationResult, AnalyticSpec, SecurityRef
from arp.storage.portfolio_store import PortfolioStore

_SYSTEM_PROMPT = f"""\
You translate a portfolio-risk question in plain language into a
structured query against a deterministic holdings aggregation engine. You
never compute or state a number yourself -- you only choose the filter,
grouping dimension, and aggregation mode that answers the question; the
engine computes the actual figure from real holdings data.

Valid group_by dimensions: {", ".join(DIMENSIONS)}.
Valid metrics: "market_value_sum" (a plain EUR exposure figure),
"weighted_avg_datapoint" (requires data_point_field_id), "count".
security_filter is a dict of dimension_name -> exact value to filter
holdings to, e.g. {{"company_id": "bmw", "asset_class": "equity"}}.
portfolio_filter is a list of portfolio_ids to restrict to; empty means
all portfolios.

If the question names a company, resolve it to a company_id using the
supplied company directory and filter on that. If you cannot confidently
resolve the company, the requested dimension isn't in the valid list, or
the question is otherwise ambiguous, set resolvable=false and explain why
in clarification_needed instead of guessing.
"""


class _ParsedQuestion(BaseModel):
    resolvable: bool
    clarification_needed: str = ""
    spec_name: str = ""
    portfolio_filter: list[str] = Field(default_factory=list)
    security_filter: dict[str, str] = Field(default_factory=dict)
    group_by: str = "portfolio_id"
    metric: str = "market_value_sum"
    data_point_field_id: str | None = None


class QAAnswer(BaseModel):
    question: str
    resolvable: bool
    clarification_needed: str = ""
    spec: AnalyticSpec | None = None
    result: AggregationResult | None = None
    answer_text: str = ""


def _company_directory(companies: dict[str, CompanyRef]) -> str:
    return "\n".join(f"{c.company_id}: {c.name}" for c in sorted(companies.values(), key=lambda c: c.name))


async def answer_question(
    question: str,
    llm: LLMClient,
    store: PortfolioStore,
    securities: dict[str, SecurityRef],
    companies: dict[str, CompanyRef],
) -> tuple[QAAnswer, LLMUsage]:
    """Parses a plain-language question into an AnalyticSpec (the LLM's
    only job), executes it with the deterministic engine (`analytics.py`),
    and returns a templated answer built from the real, computed result --
    never a number the LLM stated on its own. Same grounding discipline as
    citation checking elsewhere in this codebase: the "citation" here is
    the query itself, and `QAAnswer.spec`/`.result` always carry it so the
    answer is inspectable, not just asserted.
    """
    prompt = f"Company directory (company_id: name):\n{_company_directory(companies)}\n\nQuestion: {question}"
    parsed, usage = await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=_ParsedQuestion)

    if not parsed.resolvable:
        return QAAnswer(question=question, resolvable=False, clarification_needed=parsed.clarification_needed), usage

    spec = AnalyticSpec(
        name=parsed.spec_name or question,
        portfolio_filter=parsed.portfolio_filter,
        security_filter=parsed.security_filter,
        group_by=parsed.group_by,
        metric=parsed.metric,
        data_point_field_id=parsed.data_point_field_id,
    )
    result = analytics.execute(spec, store, securities, companies)
    if not isinstance(result, AggregationResult):
        raise ValueError("qa_agent answers point-in-time questions only; got a date_range trend spec")

    return QAAnswer(question=question, resolvable=True, spec=spec, result=result, answer_text=_template_answer(spec, result)), usage


def _template_answer(spec: AnalyticSpec, result: AggregationResult) -> str:
    filter_desc = ", ".join(f"{k}={v}" for k, v in spec.security_filter.items()) or "no filter"
    scope = f"portfolios={spec.portfolio_filter}" if spec.portfolio_filter else "all portfolios"

    if spec.metric == "market_value_sum":
        lines = [f"Total: EUR {result.total_market_value_eur:,.0f} ({scope}, {filter_desc}, grouped by {spec.group_by}, as of {result.as_of})."]
        for row in result.rows:
            lines.append(f"  {row.group_value}: EUR {row.market_value_eur:,.0f}")
        return "\n".join(lines)

    if spec.metric == "count":
        return f"{sum(r.holding_count for r in result.rows)} holdings ({scope}, {filter_desc}, as of {result.as_of})."

    lines = [f"Weighted-average {spec.data_point_field_id} by {spec.group_by} ({scope}, {filter_desc}, as of {result.as_of}):"]
    for row in result.rows:
        value = f"{row.weighted_avg_value:.4f}" if row.weighted_avg_value is not None else "no data"
        coverage = f"{row.coverage_pct:.0%}" if row.coverage_pct is not None else "n/a"
        lines.append(f"  {row.group_value}: {value} (coverage {coverage})")
    if result.unresolved_market_value_eur:
        lines.append(f"  EUR {result.unresolved_market_value_eur:,.0f} of holdings excluded for missing data.")
    return "\n".join(lines)
