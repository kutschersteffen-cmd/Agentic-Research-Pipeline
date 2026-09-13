from __future__ import annotations

from arp.replication.characteristics_data import CharacteristicPanel
from arp.replication.metrics import compute_leg_performance
from arp.replication.price_data import PricePanel
from arp.replication.rebalance import resolve_rebalance_interval_months, resolve_rebalance_months
from arp.replication.signals import assign_portfolios, compute_signal_scores
from arp.schemas.strategy_replication import BacktestResult, PortfolioPeriodReturn, SignalType, StrategySpec


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
    characteristics: CharacteristicPanel | None = None,
) -> BacktestResult:
    """Deterministic (zero-LLM) replication of `spec`'s signal + portfolio
    construction against `panel` (and, for a characteristic-based
    signal_type such as VALUE, `characteristics`).

    Implements the overlapping-portfolio construction from Jegadeesh &
    Titman (1993), generalized to an arbitrary rebalance interval (see
    arp/replication/rebalance.py): a new decile sort is formed at every
    valid rebalance date (spec.rebalance_frequency/rebalance_interval_
    months/rebalance_anchor_month), and each formed portfolio is held for
    K (holding_period_months) months; a given calendar month's long/short
    leg return is the equal-weighted average, across however many of
    those portfolios are still within their holding window, of that
    month's realized return for the stocks in each. A 1-month rebalance
    interval with K>1 reproduces Jegadeesh & Titman's own overlapping
    construction (up to K portfolios active at once); an interval equal to
    K reproduces a standard non-overlapping rebalance (exactly one
    portfolio active at a time, e.g. the classic annual value-factor
    rebalance with rebalance_frequency=ANNUAL, holding_period_months=12).
    Only equal weighting is implemented -- a `weighting` other than equal
    raises NotImplementedError.
    """
    if spec.weighting.value != "equal":
        raise NotImplementedError("run_backtest only implements equal weighting today, got " + repr(spec.weighting))
    if spec.signal_type == SignalType.VALUE and characteristics is None:
        raise ValueError("spec.signal_type is VALUE but no `characteristics` panel was supplied.")
    if characteristics is not None and characteristics.period_ends != panel.period_ends:
        raise ValueError(
            "`characteristics.period_ends` must exactly match `panel.period_ends` -- prepare the characteristics "
            "CSV on the same monthly grid as the price panel (forward-filling a less-frequently-reported "
            "fundamental onto it) rather than relying on this engine to align two different date grids."
        )

    period_ends = panel.period_ends
    k = spec.holding_period_months
    n = spec.num_portfolios
    long_bucket = spec.long_leg_portfolio
    short_bucket = spec.short_leg_portfolio
    rebalance_interval = resolve_rebalance_interval_months(spec)
    rebalance_months = resolve_rebalance_months(period_ends, rebalance_interval, spec.rebalance_anchor_month)

    formation_cache: dict[int, dict[str, int]] = {}
    periods: list[PortfolioPeriodReturn] = []
    warnings: list[str] = []
    thin_formation_periods = 0

    if spec.rebalance_anchor_month is not None and not rebalance_months:
        warnings.append(
            f"rebalance_anchor_month={spec.rebalance_anchor_month} never occurs in this panel -- no rebalance "
            "dates, so no portfolio was ever formed."
        )

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
        active_formations = sorted(f for f in rebalance_months if m - k <= f < m)
        for f in active_formations:
            if f not in formation_cache:
                scores = compute_signal_scores(spec, panel, f, characteristics=characteristics)
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
