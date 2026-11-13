from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from arp.llm.base import LLMClient, LLMUsage
from arp.portfolio import analytics, datapoint_mapping
from arp.portfolio.aggregation import DIMENSIONS
from arp.portfolio.climate.schemas import build_climate_schema
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import AggregationResult, AnalyticSpec, SecurityRef, TrendPoint
from arp.storage.portfolio_store import PortfolioStore

_SYSTEM_PROMPT = f"""\
You translate a portfolio-risk question in plain language into a
structured query against a deterministic holdings aggregation engine. You
never compute or state a number yourself -- you only choose the filter,
grouping dimension, and aggregation mode that answers the question; the
engine computes the actual figure from real holdings data.

Valid group_by dimensions: {", ".join(DIMENSIONS)}.
Valid metrics: "market_value_sum" (a plain EUR exposure figure),
"weighted_avg_datapoint" (requires data_point_field_id, a field_id from
the supplied data point directory; WACI, the weighted average carbon
intensity, is this metric on the carbon intensity field), "count".
security_filter is a dict of dimension_name -> exact value to filter
holdings to, e.g. {{"company_id": "bmw", "asset_class": "equity"}}.
portfolio_filter is a list of portfolio_ids from the supplied portfolio
directory to restrict to; empty means all portfolios.
scale is "units" (plain EUR, the default) or "millions": choose "millions"
only when the question asks for figures in EUR million.

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
    scale: Literal["units", "millions"] = "units"


class QAAnswer(BaseModel):
    question: str
    resolvable: bool
    clarification_needed: str = ""
    spec: AnalyticSpec | None = None
    result: AggregationResult | None = None
    answer_text: str = ""
    vintage: dict = {}  # holdings_as_of (+ observation_dates when a data point was used); a trend: date_range only
    trend: list[TrendPoint] | None = None  # set instead of `result` when the request names a date_range
    snapshot_dates: list[str] = Field(default_factory=list)  # the snapshot dates the figures were computed from
    scale: Literal["units", "millions"] = "units"  # how answer_text and the page write EUR; `result` stays plain EUR
    unit: str = ""


def _field_directory() -> str:
    return "\n".join(f"{f.field_id}: {f.name} ({f.unit})" for f in build_climate_schema().fields)


def _company_directory(companies: dict[str, CompanyRef]) -> str:
    return "\n".join(f"{c.company_id}: {c.name}" for c in sorted(companies.values(), key=lambda c: c.name))


async def answer_question(
    question: str,
    llm: LLMClient,
    store: PortfolioStore,
    securities: dict[str, SecurityRef],
    companies: dict[str, CompanyRef],
    *,
    portfolio_ids: list[str] | tuple[str, ...] = (),
    as_of: str | None = None,
    date_range: tuple[str, str] | None = None,
) -> tuple[QAAnswer, LLMUsage]:
    """Parses a plain-language question into an AnalyticSpec (the LLM's
    only job), executes it with the deterministic engine (`analytics.py`),
    and returns a templated answer built from the real, computed result --
    never a number the LLM stated on its own. Same grounding discipline as
    citation checking elsewhere in this codebase: the "citation" here is
    the query itself, and `QAAnswer.spec`/`.result` always carry it so the
    answer is inspectable, not just asserted.

    `portfolio_ids`, `as_of` and `date_range` are the screen's selection: the
    portfolios apply when the question names none, the dates always.
    """
    portfolios = store.list_portfolios()
    prompt = (
        f"Company directory (company_id: name):\n{_company_directory(companies)}\n\n"
        "Portfolio directory (portfolio_id: name):\n" + "\n".join(f"{p.portfolio_id}: {p.name}" for p in portfolios)
        + f"\n\nData point directory (field_id: name (unit)):\n{_field_directory()}"
        + f"\n\nQuestion: {question}"
    )
    parsed, usage = await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=_ParsedQuestion)

    if not parsed.resolvable:
        return QAAnswer(question=question, resolvable=False, clarification_needed=parsed.clarification_needed), usage

    # The model may name a portfolio by its display name. An id that matches nothing would be answered as "EUR 0".
    by_label = {label.strip().lower(): p.portfolio_id for p in portfolios for label in (p.portfolio_id, p.name)}
    unknown = [name for name in parsed.portfolio_filter if name.strip().lower() not in by_label]
    if unknown:
        known = ", ".join(f"{p.name} ({p.portfolio_id})" for p in portfolios)
        return QAAnswer(question=question, resolvable=False,
                        clarification_needed=f"No portfolio is called '{unknown[0]}'. Known portfolios: {known}."), usage
    parsed.portfolio_filter = [by_label[name.strip().lower()] for name in parsed.portfolio_filter]
    # A built-in data point named by its label gets its field id; any other id is taken as given (custom fields).
    field_ids = {f.name.lower(): f.field_id for f in build_climate_schema().fields}
    if parsed.data_point_field_id:
        parsed.data_point_field_id = field_ids.get(parsed.data_point_field_id.strip().lower(), parsed.data_point_field_id)

    def unanswered(text: str) -> tuple[QAAnswer, LLMUsage]:
        return QAAnswer(question=question, resolvable=False, clarification_needed=text), usage

    portfolio_filter = parsed.portfolio_filter or list(portfolio_ids)
    scoped = portfolio_filter or [p.portfolio_id for p in portfolios]
    dates_of = {pid: store.list_snapshot_dates(pid) for pid in scoped}
    dates = sorted({d for ds in dates_of.values() for d in ds})
    if not dates:
        return unanswered("No holdings snapshots for that selection.")
    if as_of and as_of < dates[0]:
        return unanswered(f"No holdings on or before {as_of}. The first snapshot is {dates[0]}.")
    if date_range and not any(date_range[0] <= d <= date_range[1] for d in dates):
        return unanswered(f"No snapshots between {date_range[0]} and {date_range[1]}. "
                          f"Snapshots run from {dates[0]} to {dates[-1]}.")

    spec = AnalyticSpec(
        name=parsed.spec_name or question,
        portfolio_filter=portfolio_filter,
        security_filter=parsed.security_filter,
        group_by=parsed.group_by,
        metric=parsed.metric,
        data_point_field_id=parsed.data_point_field_id,
        as_of=as_of,
        date_range=date_range,
    )
    units = {f.field_id: f.unit for f in build_climate_schema().fields}
    unit = {"market_value_sum": "EUR", "count": ""}.get(spec.metric, units.get(spec.data_point_field_id or "", ""))
    result = analytics.execute(spec, store, securities, companies)
    if not isinstance(result, AggregationResult):
        # the engine takes its dates from every portfolio; a point on a date the scoped ones have no snapshot for
        # would only repeat the snapshot before it
        trend = sorted((p for p in result if p.as_of in dates), key=lambda p: p.as_of)
        note = next((n for p in reversed(trend) if (n := _simulated_note(store, securities, spec, p.as_of))), "")
        return QAAnswer(
            question=question, resolvable=True, spec=spec, trend=trend, snapshot_dates=[p.as_of for p in trend],
            answer_text=_template_trend(spec, trend, parsed.scale) + note, vintage={"date_range": list(date_range)},
            scale=parsed.scale, unit=unit), usage

    vintage: dict = {"holdings_as_of": result.as_of}
    if spec.metric == "weighted_avg_datapoint":
        # the dates of the observations behind the average: companies held at as_of (same resolution as analytics.execute)
        held = {h.security_id for h in store.load_holdings_as_of(result.as_of, spec.portfolio_filter or None)}
        cids = {s.company_id for sid, s in securities.items() if sid in held and s.company_id}
        observations = (datapoint_mapping.resolve_field_value(store, cid, spec.data_point_field_id, result.as_of)
                        for cid in cids)
        vintage["observation_dates"] = sorted({o.observed_at[:10] for o in observations if o is not None
                                               and isinstance(o.value, (int, float)) and not isinstance(o.value, bool)})
    # each scoped portfolio's newest snapshot on or before the date: what load_holdings_as_of reads
    used = sorted({max(d for d in ds if d <= result.as_of) for ds in dates_of.values() if ds and ds[0] <= result.as_of})
    return QAAnswer(
        question=question, resolvable=True, spec=spec, result=result, vintage=vintage, snapshot_dates=used,
        answer_text=_template_answer(spec, result, parsed.scale) + _simulated_note(store, securities, spec, result.as_of),
        scale=parsed.scale, unit=unit), usage


def _simulated_note(store: PortfolioStore, securities: dict[str, SecurityRef], spec: AnalyticSpec, as_of: str) -> str:
    """A last answer line when the data point values of the companies held at `as_of` are simulated; else ""."""
    if spec.metric != "weighted_avg_datapoint":
        return ""
    held = {h.security_id for h in store.load_holdings_as_of(as_of, spec.portfolio_filter or None)}
    cids = sorted({s.company_id for sid, s in securities.items() if sid in held and s.company_id})
    note = datapoint_mapping.simulated_note(store, cids, spec.data_point_field_id, as_of)
    return f"\n  {note}" if note else ""


def _eur(value: float, scale: str) -> str:
    return f"EUR {value / 1e6:,.2f} million" if scale == "millions" else f"EUR {value:,.0f}"


def _scope_and_filter(spec: AnalyticSpec) -> tuple[str, str]:
    filter_desc = ", ".join(f"{k}={v}" for k, v in spec.security_filter.items()) or "no filter"
    return (f"portfolios={spec.portfolio_filter}" if spec.portfolio_filter else "all portfolios"), filter_desc


def _template_trend(spec: AnalyticSpec, trend: list[TrendPoint], scale: str) -> str:
    scope, filter_desc = _scope_and_filter(spec)
    start, end = spec.date_range
    lines = [f"Trend from {start} to {end}, {len(trend)} snapshots ({scope}, {filter_desc}, grouped by {spec.group_by}):"]
    for point in trend:
        if spec.metric == "market_value_sum":
            text = _eur(point.result.total_market_value_eur, scale)
        elif spec.metric == "count":
            text = f"{sum(r.holding_count for r in point.result.rows)} holdings"
        else:
            text = "; ".join(
                f"{r.group_value} " + (f"{r.weighted_avg_value:.4f}" if r.weighted_avg_value is not None else "no data")
                for r in point.result.rows)
        lines.append(f"  {point.as_of}: {text}")
    return "\n".join(lines)


def _template_answer(spec: AnalyticSpec, result: AggregationResult, scale: str = "units") -> str:
    scope, filter_desc = _scope_and_filter(spec)

    if spec.metric == "market_value_sum":
        lines = [f"Total: {_eur(result.total_market_value_eur, scale)} ({scope}, {filter_desc}, grouped by {spec.group_by}, as of {result.as_of})."]
        for row in result.rows:
            lines.append(f"  {row.group_value}: {_eur(row.market_value_eur, scale)}")
        return "\n".join(lines)

    if spec.metric == "count":
        return f"{sum(r.holding_count for r in result.rows)} holdings ({scope}, {filter_desc}, as of {result.as_of})."

    lines = [f"Weighted-average {spec.data_point_field_id} by {spec.group_by} ({scope}, {filter_desc}, as of {result.as_of}):"]
    for row in result.rows:
        value = f"{row.weighted_avg_value:.4f}" if row.weighted_avg_value is not None else "no data"
        coverage = f"{row.coverage_pct:.0%}" if row.coverage_pct is not None else "n/a"
        lines.append(f"  {row.group_value}: {value} (coverage {coverage})")
    if result.unresolved_market_value_eur:
        lines.append(f"  {_eur(result.unresolved_market_value_eur, scale)} of holdings excluded for missing data.")
    return "\n".join(lines)
