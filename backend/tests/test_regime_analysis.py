import random

from arp.replication.backtest_engine import run_backtest
from arp.replication.price_data import PricePanel
from arp.replication.regime_analysis import regime_stratified_report
from arp.schemas.strategy_replication import (
    BacktestResult,
    LegPerformance,
    PortfolioPeriodReturn,
    RebalanceFrequency,
    SignalType,
    StrategySpec,
)


def _spec() -> StrategySpec:
    return StrategySpec(
        paper_citation="Test (2020)",
        paper_title="Test paper",
        strategy_name="test momentum",
        signal_type=SignalType.MOMENTUM,
        universe_description="synthetic",
        formation_period_months=3,
        holding_period_months=3,
        num_portfolios=4,
        long_leg_portfolio=1,
        short_leg_portfolio=4,
        rebalance_frequency=RebalanceFrequency.MONTHLY,
        sample_period_start="2000-01-01",
        sample_period_end="2007-12-01",
    )


def _panel_and_benchmark(n_months=96, seed=5):
    rng = random.Random(seed)
    period_ends = []
    year, month = 2000, 1
    for _ in range(n_months):
        period_ends.append(f"{year}-{month:02d}-01")
        month += 1
        if month > 12:
            month, year = 1, year + 1
    tickers = [f"T{i}" for i in range(20)]
    returns = {t: [None] + [rng.gauss(0.01, 0.05) for _ in range(n_months - 1)] for t in tickers}
    panel = PricePanel(period_ends=period_ends, returns=returns, source="test")
    # First half calm (low vol), second half turbulent (high vol) -- a
    # deliberately non-uniform regime split so terciles are non-degenerate.
    benchmark = [None] + [
        rng.gauss(0.008, 0.02 if i < (n_months - 1) // 2 else 0.10) for i in range(n_months - 1)
    ]
    return panel, benchmark


def test_regime_stratified_report_without_benchmark_returns_explains_why():
    periods = [
        PortfolioPeriodReturn(
            period_end=f"2000-{(i % 12) + 1:02d}-01", long_return_pct=0.0, short_return_pct=0.0,
            long_short_return_pct=1.0, num_long=1, num_short=1,
        )
        for i in range(24)
    ]
    result = BacktestResult(
        spec_id="s", period_label="in_sample", period_start="2000-01-01", period_end="2001-12-01",
        data_source="test", universe_size=10, periods=periods, long_short=LegPerformance(),
    )
    report = regime_stratified_report(result)
    assert report.buckets == []
    assert "requires a benchmark series" in report.notes


def test_regime_stratified_report_too_few_observations():
    periods = [
        PortfolioPeriodReturn(
            period_end=f"2000-{(i % 12) + 1:02d}-01", long_return_pct=0.0, short_return_pct=0.0,
            long_short_return_pct=1.0, num_long=1, num_short=1, benchmark_return_pct=0.5,
        )
        for i in range(3)
    ]
    result = BacktestResult(
        spec_id="s", period_label="in_sample", period_start="2000-01-01", period_end="2000-03-01",
        data_source="test", universe_size=10, periods=periods, long_short=LegPerformance(),
    )
    report = regime_stratified_report(result, trailing_window_months=12)
    assert report.buckets == []
    assert "too few to split into terciles" in report.notes


def test_regime_stratified_report_splits_into_three_nonempty_buckets():
    spec = _spec()
    panel, benchmark = _panel_and_benchmark()
    result = run_backtest(
        spec, panel, period_label="in_sample", period_start=panel.period_ends[0], period_end=panel.period_ends[-1],
        benchmark_returns=benchmark,
    )
    report = regime_stratified_report(result)
    assert {b.regime for b in report.buckets} == {"low_volatility", "mid_volatility", "high_volatility"}
    # The first ~trailing_window_months periods have no defined trailing
    # volatility yet (not enough warm-up) and are excluded from every
    # bucket, so the bucketed total is less than or equal to, not
    # necessarily equal to, the full period count.
    assert 0 < sum(b.num_periods for b in report.buckets) <= len(result.periods)
    assert all(b.num_periods > 0 for b in report.buckets)
