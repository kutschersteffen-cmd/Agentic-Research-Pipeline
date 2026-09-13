from __future__ import annotations

from pydantic import BaseModel, Field

from arp.extraction.extractor_agent import format_evidence
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import Citation, DocumentChunk
from arp.schemas.strategy_replication import RebalanceFrequency, ReportedPerformance, SignalType, WeightingScheme

_SYSTEM_PROMPT = """\
You are a quantitative finance analyst reducing an academic 'outperformance' \
strategy paper to a precise, executable specification. You will be given \
excerpts from the paper's methodology and results sections.

Extract, strictly from what the excerpts actually say:
- The signal/ranking variable and how it is computed (formation window, \
  any skip period).
- How long a formed portfolio is held before being re-ranked.
- How many cross-sectional buckets (e.g. deciles=10, quintiles=5) the \
  universe is split into, and which bucket is bought (long_leg_portfolio) \
  vs. sold short (short_leg_portfolio) -- bucket 1 is always the HIGHEST \
  signal value, bucket num_portfolios the LOWEST, regardless of how the \
  paper itself numbers them; renumber if needed and note it in raw text.
- The universe the paper draws from (e.g. 'NYSE ordinary common shares').
- The paper's own in-sample date range.
- Its reported long/short/long-short performance (annualized return, \
  Sharpe ratio, t-statistic, alpha, volatility, max drawdown) -- leave any \
  figure the paper doesn't report as null, never estimate it.

Rules:
- NEVER invent a parameter the excerpts don't support; if genuinely \
  unclear, make your best-supported reading and set confidence low rather \
  than fabricating precision.
- Every citation's `quote` must be an EXACT, VERBATIM substring copied \
  from the evidence block, tagged with the matching doc_id.
- Provide at least one citation for the signal/holding-period definition \
  and at least one for each reported performance figure you fill in.
"""


class StrategySpecDraft(BaseModel):
    paper_title: str
    strategy_name: str
    signal_type: SignalType
    universe_description: str
    formation_period_months: int
    skip_month: bool = False
    holding_period_months: int
    rebalance_frequency: RebalanceFrequency = RebalanceFrequency.MONTHLY
    num_portfolios: int = 10
    long_leg_portfolio: int = 1
    short_leg_portfolio: int
    weighting: WeightingScheme = WeightingScheme.EQUAL
    sample_period_start: str = Field(description="ISO date YYYY-MM-DD")
    sample_period_end: str = Field(description="ISO date YYYY-MM-DD")
    reported_performance: ReportedPerformance = Field(default_factory=ReportedPerformance)
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


async def extract_strategy_spec_draft(
    paper_citation: str, chunks: list[DocumentChunk], llm: LLMClient
) -> tuple[StrategySpecDraft, LLMUsage]:
    prompt = f"Paper citation: {paper_citation}\n\nExcerpts:\n{format_evidence(chunks)}"
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=StrategySpecDraft)
