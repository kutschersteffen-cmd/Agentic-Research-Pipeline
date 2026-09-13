from __future__ import annotations

from arp.replication.metrics import compute_leg_performance
from arp.replication.price_data import PricePanel
from arp.replication.signals import assign_portfolios, compute_signal_scores
from arp.schemas.strategy_replication import BacktestResult, PortfolioPeriodReturn, RebalanceFrequency, StrategySpec


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def run_backtest(
    spec: StrategySpec,
    panel: PricePanel,
    *,
    period_label: str,
    period_start: str,
    period_end: str,
    benchmark_returns: list[float | None] | None = None,
) -> BacktestResult:
    """Deterministic (zero-LLM) replication of `spec`'s signal + portfolio
    construction against `panel`.

    Implements the overlapping-portfolio construction from Jegadeesh &
    Titman (1993): a new decile sort is formed every month, and each
    formed portfolio is held for K months; a given calendar month's
    long/short leg return is the equal-weighted average, across the up to
    K portfolios currently being held, of that month's realized return for
    the stocks in each. This is what lets a monthly return series exist
    even though each individual portfolio is only rebalanced every K
    months. Only monthly rebalancing is implemented -- spec.rebalance_
    frequency values other than MONTHLY raise NotImplementedError.
    """
    if spec.rebalance_frequency != RebalanceFrequency.MONTHLY:
        raise NotImplementedError(
            f"run_backtest only implements monthly rebalancing today, got {spec.rebalance_frequency!r}"
        )
    if spec.weighting.value != "equal":
        raise NotImplementedError("run_backtest only implements equal weighting today, got " + repr(spec.weighting))

    period_ends = panel.period_ends
    k = spec.holding_period_months
    n = spec.num_portfolios
    long_bucket = spec.long_leg_portfolio
    short_bucket = spec.short_leg_portfolio

    formation_cache: dict[int, dict[str, int]] = {}
    periods: list[PortfolioPeriodReturn] = []
    warnings: list[str] = []
    thin_formation_periods = 0

    for m in range(len(period_ends)):
        if not (period_start <= period_ends[m] <= period_end):
            # Outside this call's labeled window (e.g. an out-of-sample
            # call against a panel that also covers the in-sample years for
            # formation-lookback continuity) -- never emitted as an output
            # period, but formation_cache entries computed for earlier
            # in-window months still cover this index for later reuse.
            continue
        month_long: list[float] = []
        month_short: list[float] = []
        num_long = 0
        num_short = 0
        for f in range(max(0, m - k), m):
            if f not in formation_cache:
                scores = compute_signal_scores(spec, panel, f)
                if len(scores) < n:
                    formation_cache[f] = {}
                    if scores:
                        thin_formation_periods += 1
                else:
                    formation_cache[f] = assign_portfolios(scores, n)
            buckets = formation_cache[f]
            if not buckets:
                continue
            long_tickers = [t for t, b in buckets.items() if b == long_bucket]
            short_tickers = [t for t, b in buckets.items() if b == short_bucket]
            lr = [panel.returns[t][m] for t in long_tickers if panel.returns[t][m] is not None]
            sr = [panel.returns[t][m] for t in short_tickers if panel.returns[t][m] is not None]
            if lr:
                month_long.append(_mean(lr))  # type: ignore[arg-type]
                num_long += len(lr)
            if sr:
                month_short.append(_mean(sr))  # type: ignore[arg-type]
                num_short += len(sr)

        if not month_long or not month_short:
            continue  # warm-up window, or a period with no eligible names on one leg
        long_ret = _mean(month_long)
        short_ret = _mean(month_short)
        periods.append(
            PortfolioPeriodReturn(
                period_end=period_ends[m],
                long_return_pct=long_ret * 100,
                short_return_pct=short_ret * 100,
                long_short_return_pct=(long_ret - short_ret) * 100,
                num_long=num_long,
                num_short=num_short,
                benchmark_return_pct=(
                    benchmark_returns[m] * 100 if benchmark_returns and benchmark_returns[m] is not None else None
                ),
            )
        )

    if thin_formation_periods:
        warnings.append(
            f"{thin_formation_periods} formation month(s) had fewer than {n} eligible tickers "
            "(after requiring a full formation-period history) and contributed no portfolio."
        )
    if len(periods) < 12:
        warnings.append(f"Only {len(periods)} monthly return observation(s) -- annualized figures are unreliable.")

    long_series = [p.long_return_pct for p in periods]
    short_series = [p.short_return_pct for p in periods]
    ls_series = [p.long_short_return_pct for p in periods]
    bench_series = [p.benchmark_return_pct for p in periods]
    bench_series_clean = [b for b in bench_series if b is not None] if all(b is not None for b in bench_series) else None

    return BacktestResult(
        spec_id=spec.spec_id,
        period_label=period_label,
        period_start=period_start,
        period_end=period_end,
        data_source=panel.source,
        universe_size=len(panel.tickers()),
        periods=periods,
        long_leg=compute_leg_performance(long_series, bench_series_clean),
        short_leg=compute_leg_performance(short_series, bench_series_clean),
        long_short=compute_leg_performance(ls_series, bench_series_clean),
        avg_num_long=_mean([p.num_long for p in periods]) if periods else 0.0,
        avg_num_short=_mean([p.num_short for p in periods]) if periods else 0.0,
        warnings=warnings,
    )
