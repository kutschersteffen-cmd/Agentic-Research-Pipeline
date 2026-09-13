from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from arp.schemas.common import Citation, ProvenanceInfo, new_id, now_iso


class SignalType(StrEnum):
    """Which deterministic signal implementation in arp/replication/signals.py
    computes this spec's cross-sectional score. Extend as more strategy
    families are added; each needs a matching function in signals.py."""

    MOMENTUM = "momentum"
    VALUE = "value"
    """A cross-sectional sort on a fundamental characteristic (e.g.
    book-to-market), read from a CharacteristicDataSource rather than
    computed from price history -- see StrategySpec.characteristic_name/
    characteristic_lag_months. Unrelated to WeightingScheme.VALUE
    ("value-weighted" = market-cap-weighted, the standard finance sense of
    that term) -- the two fields (signal_type vs. weighting) disambiguate."""
    TEXT_SENTIMENT = "text_sentiment"
    """A cross-sectional sort on an LLM-scored sentiment characteristic
    derived from news/earnings-call/transcript text (arp/replication/
    sentiment_scoring.py) -- mechanically identical to VALUE (same
    characteristic_name/characteristic_lag_months fields, same
    CharacteristicDataSource plumbing), kept as its own SignalType only so
    a spec/report is self-describing about where the ranking signal came
    from, and so ReportedPerformance comparisons and docs can call out the
    hindsight-risk considerations specific to LLM-scored historical text
    (see docs/STRATEGY_REPLICATION_METHODOLOGY.md)."""
    COMPOSITE = "composite"
    """A weighted rank-average of two or more other signals (e.g. momentum
    + value) -- see StrategySpec.composite_components and
    arp/replication/signals.py::composite_scores. A component's signal_type
    must not itself be COMPOSITE (no nesting)."""


class WeightingScheme(StrEnum):
    EQUAL = "equal"
    VALUE = "value"


class RebalanceFrequency(StrEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"
    CUSTOM = "custom"
    """Any other schedule a paper specifies -- pair with
    StrategySpec.rebalance_interval_months (required) and, optionally,
    rebalance_anchor_month, rather than adding a new enum member per paper.
    See arp/replication/rebalance.py::resolve_rebalance_interval_months."""


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


class CompositeSignalComponent(BaseModel):
    """One sub-signal inside a COMPOSITE StrategySpec -- the same
    per-signal parameters a standalone MOMENTUM/VALUE/TEXT_SENTIMENT spec
    would carry, minus everything about portfolio construction (buckets,
    legs, holding period, rebalancing), which is decided once at the
    composite level, not per component."""

    signal_type: SignalType = Field(description="MOMENTUM, VALUE, or TEXT_SENTIMENT -- never COMPOSITE (no nesting).")
    weight: float = Field(gt=0.0, description="Relative weight in the rank-average; weights need not sum to 1 (they're normalized per-ticker by the weight actually applied -- see composite_scores).")
    formation_period_months: int = Field(default=0, description="MOMENTUM only.")
    skip_month: bool = Field(default=False, description="MOMENTUM only.")
    characteristic_name: str | None = Field(default=None, description="VALUE/TEXT_SENTIMENT only.")
    characteristic_lag_months: int = Field(default=0, description="VALUE/TEXT_SENTIMENT only.")


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

    formation_period_months: int = Field(default=0, description="MOMENTUM only: lookback window (J) the signal is computed over. Ignored (leave 0) for a characteristic-based signal_type such as VALUE, where compute_signal_scores instead reads characteristic_name/characteristic_lag_months.")
    skip_month: bool = Field(default=False, description="MOMENTUM only: skip the most recent month between formation and holding, as some momentum papers do to avoid short-term reversal/microstructure effects. Ignored for a characteristic-based signal_type.")
    holding_period_months: int = Field(description="How long a formed portfolio is held (K) before being re-ranked. Used by every signal_type.")
    rebalance_frequency: RebalanceFrequency = Field(
        default=RebalanceFrequency.MONTHLY,
        description="How often a new portfolio is formed. MONTHLY/QUARTERLY/ANNUAL imply an interval of 1/3/12 "
        "months; CUSTOM reads rebalance_interval_months directly for any other schedule (e.g. every 2 months, "
        "every 18 months) a paper specifies -- see arp/replication/rebalance.py.",
    )
    rebalance_interval_months: int | None = Field(
        default=None,
        ge=1,
        description="Required when rebalance_frequency=CUSTOM: how often, in months, a new portfolio is formed. "
        "Ignored for MONTHLY/QUARTERLY/ANNUAL, which imply their own fixed interval regardless of this field.",
    )
    rebalance_anchor_month: int | None = Field(
        default=None,
        ge=1,
        le=12,
        description="Optional calendar month (1=Jan..12=Dec) rebalances are anchored to, instead of simply every "
        "`interval` months counted from the start of the fetched price panel -- e.g. 6 (June) with "
        "rebalance_frequency=ANNUAL reproduces the classic Fama & French June-aligned annual rebalance, or 2 "
        "(Feb) with QUARTERLY rebalances every Feb/May/Aug/Nov. Meaningless (ignored) when the effective interval "
        "is 1 month, since every month is already a rebalance month.",
    )
    characteristic_name: str | None = Field(
        default=None,
        description="VALUE/TEXT_SENTIMENT (or any future characteristic-based signal_type) only: name of the "
        "fundamental/derived field the signal ranks on, e.g. 'book_to_market' or 'news_sentiment' -- must match a "
        "column a CharacteristicDataSource can serve (arp/replication/characteristics_data.py). Purely a label "
        "here; the actual data comes from whichever CharacteristicDataSource the caller supplies to run_replication.",
    )
    characteristic_lag_months: int = Field(
        default=0,
        description="VALUE/TEXT_SENTIMENT (or any future characteristic-based signal_type) only: how many months "
        "to lag the characteristic behind the ranking month, so the score reflects a value that was actually "
        "public at that time rather than a look-ahead figure (e.g. a fiscal-year-end book value isn't public "
        "until months later; a news article's sentiment is public immediately, so 0 is typical there). Ignored "
        "for MOMENTUM, which uses formation_period_months/skip_month instead.",
    )
    composite_components: list[CompositeSignalComponent] = Field(
        default_factory=list,
        description="Required (2+) when signal_type=COMPOSITE: the sub-signals combined via weighted rank-"
        "averaging -- see arp/replication/signals.py::composite_scores. Ignored for every other signal_type.",
    )
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
    provenance: ProvenanceInfo = Field(
        default_factory=ProvenanceInfo,
        description="Which extractor/verifier model + prompt-version produced this spec, mirroring ExtractedField's "
        "provenance in arp/extraction -- a later prompt/model change is detectable against a previously persisted "
        "spec instead of silently mixing pipeline versions. Left at its all-None default for a hand-authored spec "
        "(see arp/replication/data/*.json), never fabricated.",
    )

    extraction_notes: str = Field(default="", description="Caveats about this spec: simplifications versus the paper's exact methodology, data limitations, etc. Always populate this for a hand-authored worked-example spec.")
    num_trials_attempted: int = Field(
        default=1,
        ge=1,
        description="How many distinct strategy variants (alternative signals, universes, parameter values, ...) "
        "were effectively tried before arriving at this exact spec -- a hand-picked count, not something inferred "
        "from the backtest itself. Feeds the multiple-testing-aware significance hurdle and the Deflated Sharpe "
        "Ratio in compare.py/deflated_sharpe.py (Harvey, Liu & Zhu 2016; Bailey & Lopez de Prado's Deflated Sharpe "
        "Ratio): the default of 1 means 'no multiple-testing adjustment' (this exact spec was the only one "
        "considered), which is honest only when that's actually true -- a paper that tried many factors/parameter "
        "combinations and reported the best one should set this to that count, or the significance read here will "
        "overstate how surprising the result is.",
    )
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


class DeflatedSharpeAssessment(BaseModel):
    """Output of arp/replication/deflated_sharpe.py's Probabilistic/
    Deflated Sharpe Ratio computation (Bailey & Lopez de Prado) for one
    leg's monthly return series -- a multiple-testing-aware complement to
    the plain t-stat check in compare.py, not a replacement for it: a
    result can pass the plain t-stat hurdle and still fail here once the
    number of variants actually tried (StrategySpec.num_trials_attempted)
    is accounted for.

    All Sharpe-ratio fields are in PER-PERIOD (monthly) units, not
    annualized -- the PSR/DSR formulas are derived in per-period units,
    and annualizing first would silently misapply them.
    """

    n_obs: int
    n_trials: int
    sharpe_ratio_period: float | None = None
    skewness: float | None = None
    kurtosis: float | None = None
    expected_max_sharpe_under_null_period: float | None = Field(
        default=None, description="E[max Sharpe] expected from n_trials variants under zero true skill -- the DSR benchmark."
    )
    probabilistic_sharpe_ratio: float | None = Field(
        default=None, description="PSR(0): probability the TRUE per-period Sharpe ratio exceeds zero, given n_obs/skew/kurtosis. Ignores n_trials."
    )
    deflated_sharpe_ratio: float | None = Field(
        default=None,
        description="PSR(expected_max_sharpe_under_null): probability the true Sharpe ratio exceeds what pure luck across n_trials variants would produce. The trial-count-aware figure; prefer this over probabilistic_sharpe_ratio whenever n_trials > 1.",
    )
    notes: str = ""


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
    deflated_sharpe: DeflatedSharpeAssessment | None = Field(
        default=None,
        description="Multiple-testing-aware Sharpe-ratio assessment of the in-sample long-short leg (see "
        "arp/replication/deflated_sharpe.py), computed whenever there are enough in-sample periods to estimate "
        "one. None does not mean 'passed' -- it means there wasn't enough data to compute it at all.",
    )
    verdict: ReplicationVerdict
    verdict_notes: str = ""
    generated_at: str = Field(default_factory=now_iso)
