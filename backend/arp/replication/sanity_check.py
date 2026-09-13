from __future__ import annotations

from pydantic import BaseModel, Field

from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.strategy_replication import ReplicationComparisonReport, StrategySpec

_SYSTEM_PROMPT = """\
You are a skeptical quantitative research reviewer performing a \
qualitative sanity check on a strategy backtest that was already computed \
deterministically by other code -- you cannot see or re-run that \
computation, and nothing you say here verifies or re-derives the numbers. \
Your only job is to flag anything about the RESULT that a seasoned quant \
would find suspicious enough to investigate further:
- A Sharpe ratio, annualized return, or t-stat far outside what's \
  plausible for a real market anomaly (e.g. an annualized Sharpe above \
  roughly 3, or an annualized return above roughly 100%, on a long-short \
  equity strategy) is a classic sign of a bug, a data error, or \
  overfitting -- not real alpha.
- A very small universe, very few return observations, or a long-short \
  spread built from only 1-2 names per leg makes any statistic unreliable \
  regardless of how significant it looks.
- A dramatic in-sample vs. out-of-sample gap, especially combined with a \
  large number of free parameters (num_portfolios, holding period, \
  rebalance schedule) relative to the sample length, is a classic \
  overfitting signature.
- Reported performance suspiciously close to a round number, or matching \
  the in-sample replication to many decimal places, can indicate the \
  comparison wasn't actually independent.

Be specific about WHY each concern applies to the actual figures given, \
citing the real numbers -- not generic disclaimers. If nothing looks \
suspicious, say so plainly rather than inventing a concern."""


class SanityCheckFinding(BaseModel):
    concern: str = Field(description="Short label, e.g. 'implausible_sharpe', 'thin_universe', 'overfitting_signature'.")
    explanation: str = Field(description="Why this specific result triggers the concern -- cite the actual number(s).")


class SanityCheckAssessment(BaseModel):
    """A qualitative, LLM-generated second opinion on an already-computed
    ReplicationComparisonReport -- advisory only. This is deliberately NOT
    grounded/verified the way an extraction elsewhere in this codebase is:
    there is no source document to check a quote against, only an opinion
    about whether a set of numbers looks statistically plausible. Never
    treat `plausible=True` as validation, or `plausible=False` as proof of
    a bug -- it's a prompt for a human to look closer, nothing more.
    """

    plausible: bool = Field(description="Overall: does this look like a real, robust finding rather than a likely artifact/bug/overfit?")
    findings: list[SanityCheckFinding] = Field(default_factory=list)
    summary: str


def _report_summary_for_prompt(spec: StrategySpec, report: ReplicationComparisonReport) -> str:
    lines = [
        f"Strategy: {spec.strategy_name} ({spec.signal_type.value}, {spec.paper_citation})",
        f"Universe size: {report.in_sample.universe_size}, num_portfolios: {spec.num_portfolios}, "
        f"holding_period_months: {spec.holding_period_months}, rebalance: {spec.rebalance_frequency.value}",
        f"In-sample: {len(report.in_sample.periods)} periods, avg_num_long={report.in_sample.avg_num_long:.1f}, "
        f"avg_num_short={report.in_sample.avg_num_short:.1f}",
        f"In-sample long-short: annualized_return={report.in_sample.long_short.annualized_return_pct}, "
        f"sharpe={report.in_sample.long_short.sharpe_ratio}, t_stat={report.in_sample.long_short.t_stat}, "
        f"max_drawdown={report.in_sample.long_short.max_drawdown_pct}",
    ]
    if report.out_of_sample is not None:
        lines.append(
            f"Out-of-sample ({len(report.out_of_sample.periods)} periods) long-short: "
            f"annualized_return={report.out_of_sample.long_short.annualized_return_pct}, "
            f"sharpe={report.out_of_sample.long_short.sharpe_ratio}"
        )
    lines.append(
        "Paper's reported long-short: annualized_return="
        f"{report.reported_performance.long_short.annualized_return_pct}"
    )
    lines.append(f"Verdict: {report.verdict.value} -- {report.verdict_notes}")
    return "\n".join(lines)


async def sanity_check_report(
    spec: StrategySpec, report: ReplicationComparisonReport, llm: LLMClient
) -> tuple[SanityCheckAssessment, LLMUsage]:
    """One LLM call reviewing an already-completed ReplicationComparisonReport
    for statistical plausibility (implausible Sharpe/return, a too-thin
    universe, an overfitting signature, a suspicious in/out-of-sample
    match) -- the AFI ("complement, never replace") pattern applied to
    this module's own output: the deterministic numbers are never
    recomputed or second-guessed here, only reviewed qualitatively.
    """
    prompt = _report_summary_for_prompt(spec, report)
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=SanityCheckAssessment)
