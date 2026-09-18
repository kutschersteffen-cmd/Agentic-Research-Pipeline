from __future__ import annotations

import numpy as np

from arp.schemas.strategy_replication import LegPerformance

_PERIODS_PER_YEAR = 12
# A genuinely constant return series can still show a nonzero np.std() on
# the order of 1e-17/1e-18 -- floating-point noise from the variance
# formula's subtractions, not real dispersion. Gating on a plain `> 0`
# turns that noise into an absurd Sharpe/t-stat/beta (division by ~1e-18).
# This threshold is well above float64 noise for any realistic return
# series (percentages divided by 100, so O(1e-4) scale) and well below any
# real volatility worth reporting.
_ZERO_VOLATILITY_EPSILON = 1e-10


def compute_leg_performance(
    monthly_returns_pct: list[float], benchmark_monthly_returns_pct: list[float] | None = None
) -> LegPerformance:
    """Standard performance statistics for one monthly return series
    (percent units in, percent units out), matching the field names on
    ReportedPerformance's LegPerformance so a paper's reported numbers and
    a replication's measured numbers are directly comparable in compare.py.

    Annualized return is geometric (CAGR-style compounding), not the mean
    return scaled by 12 -- consistent with how return series are usually
    annualized and with max-drawdown using the same compounded path.
    """
    if not monthly_returns_pct:
        return LegPerformance()

    r = np.asarray(monthly_returns_pct, dtype=float) / 100.0
    n = len(r)
    mean_r = float(r.mean())
    std_r = float(r.std(ddof=1)) if n > 1 else 0.0

    compounded = float(np.prod(1.0 + r))
    annualized_return = compounded ** (_PERIODS_PER_YEAR / n) - 1.0 if compounded > 0 else -1.0
    annualized_vol = std_r * (_PERIODS_PER_YEAR**0.5)
    has_real_volatility = std_r > _ZERO_VOLATILITY_EPSILON
    sharpe = (mean_r * _PERIODS_PER_YEAR) / annualized_vol if has_real_volatility else None
    t_stat = (mean_r / (std_r / (n**0.5))) if has_real_volatility and n > 1 else None

    cum = np.cumprod(1.0 + r)
    running_max = np.maximum.accumulate(cum)
    drawdowns = cum / running_max - 1.0
    max_drawdown = float(drawdowns.min()) if len(drawdowns) else None

    alpha_annualized: float | None = None
    beta: float | None = None
    if benchmark_monthly_returns_pct and len(benchmark_monthly_returns_pct) == n and n > 1:
        b = np.asarray(benchmark_monthly_returns_pct, dtype=float) / 100.0
        if b.std() > _ZERO_VOLATILITY_EPSILON:
            slope, intercept = np.polyfit(b, r, 1)
            beta = float(slope)
            alpha_annualized = float((1.0 + intercept) ** _PERIODS_PER_YEAR - 1.0)

    return LegPerformance(
        annualized_return_pct=annualized_return * 100,
        monthly_mean_return_pct=mean_r * 100,
        annualized_volatility_pct=annualized_vol * 100,
        sharpe_ratio=sharpe,
        t_stat=t_stat,
        max_drawdown_pct=max_drawdown * 100 if max_drawdown is not None else None,
        alpha_annualized_pct=alpha_annualized * 100 if alpha_annualized is not None else None,
        beta=beta,
    )
