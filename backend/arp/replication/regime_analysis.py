from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field

from arp.replication.metrics import compute_leg_performance
from arp.schemas.strategy_replication import BacktestResult, LegPerformance

_MIN_VALID_TRAILING_VOL_OBSERVATIONS = 6


class RegimeBucketPerformance(BaseModel):
    regime: str = Field(description="'low_volatility', 'mid_volatility', or 'high_volatility'.")
    num_periods: int
    long_short: LegPerformance = Field(default_factory=LegPerformance)


class RegimeStratifiedReport(BaseModel):
    """Long-short performance broken out by trailing-volatility regime
    (terciles of the benchmark's own trailing realized volatility) rather
    than pooled across the whole sample -- inspired by arXiv 2512.12924
    ("Interpretable Hypothesis-Driven Trading")'s finding that a strategy's
    performance can be strongly regime-dependent even when its full-sample
    average looks unremarkable: averaging across regimes can hide a
    strategy that only works in calm markets (or only in turbulent ones),
    which a paper's single full-sample Sharpe ratio would never reveal.

    Regimes are classified from the BENCHMARK's own trailing volatility,
    never the strategy's own return series -- classifying by the
    strategy's own volatility would be circular (its returns partly
    define the buckets it's then evaluated within).
    """

    trailing_window_months: int
    buckets: list[RegimeBucketPerformance] = Field(default_factory=list)
    notes: str = ""


def _trailing_volatility(benchmark_returns_pct: list[float | None], window: int) -> list[float | None]:
    vols: list[float | None] = []
    for i in range(len(benchmark_returns_pct)):
        window_slice = benchmark_returns_pct[max(0, i - window + 1) : i + 1]
        clean = [v for v in window_slice if v is not None]
        if len(clean) < max(2, window // 2):
            vols.append(None)
            continue
        vols.append(float(np.asarray(clean, dtype=float).std(ddof=1)))
    return vols


def regime_stratified_report(result: BacktestResult, *, trailing_window_months: int = 12) -> RegimeStratifiedReport:
    """Splits `result.periods` into low/mid/high trailing-volatility
    terciles (using each period's `benchmark_return_pct`, which is only
    populated when `run_backtest` was called with `benchmark_returns`) and
    reports the long-short leg's performance separately within each --
    zero-LLM, deterministic, same as the rest of backtest_engine.py.
    """
    benchmark_series = [p.benchmark_return_pct for p in result.periods]
    if all(b is None for b in benchmark_series):
        return RegimeStratifiedReport(
            trailing_window_months=trailing_window_months,
            notes="No benchmark_return_pct available on this BacktestResult's periods -- regime stratification "
            "requires a benchmark series (pass benchmark_returns into run_backtest); classifying regimes by the "
            "strategy's OWN return volatility instead would be circular.",
        )

    trailing_vol = _trailing_volatility(benchmark_series, trailing_window_months)
    valid_vols = sorted(v for v in trailing_vol if v is not None)
    if len(valid_vols) < _MIN_VALID_TRAILING_VOL_OBSERVATIONS:
        return RegimeStratifiedReport(
            trailing_window_months=trailing_window_months,
            notes=f"Only {len(valid_vols)} period(s) have a defined trailing volatility (need a full "
            f"{trailing_window_months}-month-ish warm-up) -- too few to split into terciles.",
        )

    n = len(valid_vols)
    low_cut = valid_vols[n // 3]
    high_cut = valid_vols[(2 * n) // 3]

    bucket_indices: dict[str, list[int]] = {"low_volatility": [], "mid_volatility": [], "high_volatility": []}
    for i, v in enumerate(trailing_vol):
        if v is None:
            continue
        if v <= low_cut:
            bucket_indices["low_volatility"].append(i)
        elif v <= high_cut:
            bucket_indices["mid_volatility"].append(i)
        else:
            bucket_indices["high_volatility"].append(i)

    buckets = [
        RegimeBucketPerformance(
            regime=regime,
            num_periods=len(idxs),
            long_short=compute_leg_performance([result.periods[i].long_short_return_pct for i in idxs]),
        )
        for regime, idxs in bucket_indices.items()
    ]

    return RegimeStratifiedReport(
        trailing_window_months=trailing_window_months,
        buckets=buckets,
        notes=f"Regime terciles computed from the benchmark's own trailing {trailing_window_months}-month realized volatility.",
    )
