from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from arp.schemas.common import Citation, new_id, now_iso


class SignalType(StrEnum):
    """Which deterministic signal implementation in arp/replication/signals.py
    computes this spec's cross-sectional score. Extend as more strategy
    families are added; each needs a matching function in signals.py."""

    MOMENTUM = "momentum"


class WeightingScheme(StrEnum):
    EQUAL = "equal"
    VALUE = "value"


class RebalanceFrequency(StrEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class LegPerformance(BaseModel):
    """One portfolio leg's (long, short, or long-short spread) performance --
    either as reported by the paper, or as measured by a replication
    backtest (arp/replication/metrics.py computes the latter with identical
    field names so the two are directly comparable in compare.py)."""

    annualized_return_pct: float | None = None
    monthly_mean_return_pct: float | None = None
    annualized_volatility_pct: float | None = None
    sharpe_ratio: float | None = None
    t_stat: float | None = None
    max_drawdown_pct: float | None = None
    alpha_annualized_pct: float | None = None
    beta: float | None = None


class ReportedPerformance(BaseModel):
    """Performance as reported by the paper itself -- transcribed (or
    LLM-extracted + grounded) from its results tables, never computed.
    Any leg left as a default LegPerformance() means the paper didn't
    report that figure, not that it was zero."""

    long_leg: LegPerformance = Field(default_factory=LegPerformance)
    short_leg: LegPerformance = Field(default_factory=LegPerformance)
    long_short: LegPerformance = Field(default_factory=LegPerformance)
    benchmark_name: str | None = None
    notes: str = ""


class StrategySpec(BaseModel):
    """The methodology of one academic 'outperformance' strategy paper,
    reduced to parameters the deterministic backtest engine
    (arp/replication/backtest_engine.py) can execute directly. Produced
    either by hand (see arp/replication/data/*.json for worked examples) or
    by the extractor/verifier pipeline in arp/replication/spec_extraction.py,
    which grounds every extracted field against the source paper text the
    same way any other extraction in this codebase is grounded.
    """

    spec_id: str = Field(default_factory=lambda: new_id("spec"))
    paper_citation: str = Field(description="Full citation, e.g. 'Jegadeesh & Titman (1993), Journal of Finance 48(1).'")
    paper_title: str
    strategy_name: str

    signal_type: SignalType
    universe_description: str = Field(description="e.g. 'NYSE/AMEX ordinary common shares' -- as defined by the paper, not necessarily what a given backtest run actually uses.")

    formation_period_months: int = Field(description="Lookback window (J) the signal is computed over.")
    skip_month: bool = Field(default=False, description="Skip the most recent month between formation and holding, as some momentum papers do to avoid short-term reversal/microstructure effects.")
    holding_period_months: int = Field(description="How long a formed portfolio is held (K) before being rebalanced.")
    rebalance_frequency: RebalanceFrequency = Field(default=RebalanceFrequency.MONTHLY)
    num_portfolios: int = Field(default=10, description="Number of cross-sectional buckets the signal splits the universe into, e.g. 10 for deciles.")
    long_leg_portfolio: int = Field(default=1, description="1-indexed portfolio bucket that is bought, ranked best-signal-first (bucket 1 = highest signal).")
    short_leg_portfolio: int = Field(description="1-indexed portfolio bucket that is sold short.")
    weighting: WeightingScheme = Field(default=WeightingScheme.EQUAL)

    sample_period_start: str = Field(description="ISO date (YYYY-MM-DD), the paper's own in-sample start.")
    sample_period_end: str = Field(description="ISO date (YYYY-MM-DD), the paper's own in-sample end.")

    reported_performance: ReportedPerformance = Field(default_factory=ReportedPerformance)

    citations: list[Citation] = Field(default_factory=list, description="Grounded quotes from the source paper backing the fields above.")
    grounded: bool = Field(default=False, description="True only if every citation in `citations` passed the programmatic grounding check.")
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    needs_review: bool = False
    verifier_notes: str | None = None

    extraction_notes: str = Field(default="", description="Caveats about this spec: simplifications versus the paper's exact methodology, data limitations, etc. Always populate this for a hand-authored worked-example spec.")
    created_at: str = Field(default_factory=now_iso)


class PortfolioPeriodReturn(BaseModel):
    """One rebalance period's realized return for one leg, plus how many
    names were actually available -- lets a thin/illiquid period be spotted
    rather than silently averaged in with everything else."""

    period_end: str
    long_return_pct: float
    short_return_pct: float
    long_short_return_pct: float
    num_long: int
    num_short: int
    benchmark_return_pct: float | None = None


class BacktestResult(BaseModel):
    """A deterministic (zero-LLM) replication of one StrategySpec's signal
    and portfolio construction over one date window, against whatever price
    panel a PriceDataSource supplied -- see arp/replication/backtest_engine.py.
    """

    result_id: str = Field(default_factory=lambda: new_id("bt"))
    spec_id: str
    period_label: str = Field(description="'in_sample' (the paper's own sample_period) or 'out_of_sample' (any other window run against the same rules).")
    period_start: str
    period_end: str
    data_source: str = Field(description="Which PriceDataSource implementation produced the panel, e.g. 'csv' or 'yfinance' -- material to how much the replication can be trusted.")
    universe_size: int = Field(description="Number of distinct tickers in the panel actually used.")
    periods: list[PortfolioPeriodReturn] = Field(default_factory=list)

    long_leg: LegPerformance = Field(default_factory=LegPerformance)
    short_leg: LegPerformance = Field(default_factory=LegPerformance)
    long_short: LegPerformance = Field(default_factory=LegPerformance)
    avg_num_long: float = 0.0
    avg_num_short: float = 0.0
    monthly_turnover_pct: float | None = None
    warnings: list[str] = Field(default_factory=list, description="Data-quality caveats, e.g. thin coverage in early periods, gaps in the panel.")
    generated_at: str = Field(default_factory=now_iso)


class ReplicationVerdict(StrEnum):
    REPLICATED = "replicated"
    """In-sample long-short performance is directionally consistent with,
    and not a large downgrade from, the paper's own reported figures."""
    PARTIALLY_REPLICATED = "partially_replicated"
    """Same sign but a material magnitude gap versus the paper."""
    NOT_REPLICATED = "not_replicated"
    """Wrong sign, or the effect is statistically indistinguishable from
    zero in-sample."""
    DECAYED_OUT_OF_SAMPLE = "decayed_out_of_sample"
    """Replicated in-sample, but the effect weakens or disappears in the
    out-of-sample window -- the finding usually of most interest for an
    'outperformance' claim."""
    INSUFFICIENT_DATA = "insufficient_data"


class ReplicationComparisonReport(BaseModel):
    """The end product of one replication run: in-sample vs. the paper's
    own reported numbers, plus an out-of-sample read on whether the effect
    persists. See arp/replication/compare.py for the verdict logic."""

    report_id: str = Field(default_factory=lambda: new_id("rep"))
    spec_id: str
    in_sample: BacktestResult
    out_of_sample: BacktestResult | None = None
    reported_performance: ReportedPerformance
    in_sample_return_gap_pp: float | None = Field(default=None, description="In-sample long-short annualized return minus the paper's reported figure, in percentage points. Negative means the replication underperforms the paper.")
    out_of_sample_return_gap_pp: float | None = Field(default=None, description="Out-of-sample long-short annualized return minus the in-sample replication's own annualized return, in percentage points -- decay/persistence, not a comparison to the paper.")
    verdict: ReplicationVerdict
    verdict_notes: str = ""
    generated_at: str = Field(default_factory=now_iso)
