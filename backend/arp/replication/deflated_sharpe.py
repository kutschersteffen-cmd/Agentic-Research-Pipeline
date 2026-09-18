from __future__ import annotations

import math

import numpy as np

from arp.schemas.strategy_replication import DeflatedSharpeAssessment

_EULER_MASCHERONI = 0.5772156649015329
_MIN_OBS_FOR_HIGHER_MOMENTS = 3


def _skew_kurtosis(returns: np.ndarray) -> tuple[float, float]:
    """Sample skewness and (plain, non-excess) kurtosis of a return series,
    computed by hand since this codebase has no scipy dependency. Uses the
    biased third/fourth standardized moments -- matching the convention
    Bailey & Lopez de Prado's Probabilistic/Deflated Sharpe Ratio formulas
    assume (kurtosis=3 for a normal distribution, not "excess" kurtosis=0).
    Falls back to the normal distribution's own moments (skew=0,
    kurtosis=3) when there's too little data or no dispersion to estimate
    higher moments meaningfully -- that reduces the PSR/DSR formula below
    to its plain (Gaussian-returns) form rather than raising.
    """
    n = len(returns)
    if n < _MIN_OBS_FOR_HIGHER_MOMENTS:
        return 0.0, 3.0
    std = float(returns.std(ddof=0))
    if std <= 1e-12:
        return 0.0, 3.0
    z = (returns - returns.mean()) / std
    return float(np.mean(z**3)), float(np.mean(z**4))


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inverse standard normal CDF via Peter Acklam's rational
    approximation (accurate to ~1.15e-9) -- the one spot this module needs
    it (the expected maximum Sharpe ratio under repeated trials, below),
    kept dependency-free rather than pulling in scipy for a single call.
    """
    if not 0.0 < p < 1.0:
        raise ValueError("p must be strictly between 0 and 1")
    a = (-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02, 1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00)
    b = (-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02, 6.680131188771972e01, -1.328068155288572e01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00, -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00)
    p_low = 0.02425
    p_high = 1 - p_low
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)


def probabilistic_sharpe_ratio(
    observed_sharpe_period: float,
    benchmark_sharpe_period: float,
    n_obs: int,
    skew: float,
    kurtosis: float,
) -> float:
    """PSR(SR*): the probability, per Bailey & Lopez de Prado ("The Sharpe
    Ratio Efficient Frontier"), that the TRUE per-period Sharpe ratio
    exceeds `benchmark_sharpe_period`, given `n_obs` observations of a
    return series with sample skew/kurtosis `skew`/`kurtosis` -- a
    negatively-skewed or fat-tailed series needs a longer sample to trust
    the same observed Sharpe ratio at face value.

    Both Sharpe ratios must already be in the SAME per-period (not
    annualized) units: the n_obs/skew/kurtosis correction below is derived
    in per-period units, and annualizing first would silently misapply it.
    """
    if n_obs < 2:
        return float("nan")
    denom = 1.0 - skew * observed_sharpe_period + ((kurtosis - 1.0) / 4.0) * observed_sharpe_period**2
    if denom <= 0:
        denom = 1e-12
    z = (observed_sharpe_period - benchmark_sharpe_period) * math.sqrt(n_obs - 1) / math.sqrt(denom)
    return _norm_cdf(z)


def expected_max_sharpe_under_trials(n_trials: int, sharpe_variance_across_trials: float) -> float:
    """E[max Sharpe ratio] expected from `n_trials` independent strategy
    trials of per-period-Sharpe variance `sharpe_variance_across_trials`,
    under the null that NONE of them has any true skill -- Bailey & Lopez
    de Prado's "Deflated Sharpe Ratio" benchmark. Trying many variants
    (parameter sweeps, alternative universes, alternative signals) and
    reporting only the best-looking one mechanically inflates the best
    observed Sharpe ratio even with zero true edge; this is how much of
    that inflation to expect and discount for, before ever looking at
    which variant is "the" strategy.
    """
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    if n_trials == 1:
        return 0.0
    sigma = math.sqrt(max(sharpe_variance_across_trials, 0.0))
    if sigma == 0.0:
        return 0.0
    return sigma * (
        (1 - _EULER_MASCHERONI) * _norm_ppf(1 - 1.0 / n_trials) + _EULER_MASCHERONI * _norm_ppf(1 - 1.0 / (n_trials * math.e))
    )


def deflated_sharpe_ratio(
    monthly_returns_pct: list[float],
    *,
    n_trials: int,
    sharpe_variance_across_trials: float | None = None,
) -> DeflatedSharpeAssessment:
    """Full DSR/PSR assessment of one leg's monthly return series.

    `n_trials` is the number of strategy variants effectively considered
    before this one was reported (StrategySpec.num_trials_attempted) --
    pass 1 (the default there) for "we only ever tried this exact spec",
    which collapses the deflation term to zero and leaves DSR == PSR(0).

    `sharpe_variance_across_trials`, when not supplied, is approximated as
    this series' own Sharpe-ratio ESTIMATION variance -- (1 - skew*SR +
    (kurtosis-1)/4*SR^2) / (n_obs - 1), the same quantity PSR's own
    denominator uses -- treating the N trials as if each had been
    estimated with comparable precision to this one. That is a simplifying
    stand-in for the true (usually unobserved) cross-trial Sharpe
    variance, not a re-derivation of Bailey & Lopez de Prado's own
    empirical-trials formula; pass an explicit value instead when the
    actual distribution of trial Sharpe ratios is known (e.g. from a CPCV
    sweep -- see arp/replication/cpcv.py).
    """
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    r = np.asarray(monthly_returns_pct, dtype=float) / 100.0
    n_obs = len(r)
    if n_obs < 2:
        return DeflatedSharpeAssessment(
            n_obs=n_obs,
            n_trials=n_trials,
            sharpe_ratio_period=None,
            skewness=None,
            kurtosis=None,
            expected_max_sharpe_under_null_period=None,
            probabilistic_sharpe_ratio=None,
            deflated_sharpe_ratio=None,
            notes="Fewer than 2 monthly observations -- cannot estimate a Sharpe ratio, let alone PSR/DSR.",
        )
    mean_r = float(r.mean())
    std_r = float(r.std(ddof=1))
    sharpe_period = mean_r / std_r if std_r > 1e-12 else None
    skew, kurtosis = _skew_kurtosis(r)

    if sharpe_period is None:
        return DeflatedSharpeAssessment(
            n_obs=n_obs,
            n_trials=n_trials,
            sharpe_ratio_period=None,
            skewness=skew,
            kurtosis=kurtosis,
            expected_max_sharpe_under_null_period=None,
            probabilistic_sharpe_ratio=None,
            deflated_sharpe_ratio=None,
            notes="Zero return volatility -- Sharpe ratio (and PSR/DSR) undefined.",
        )

    if sharpe_variance_across_trials is None:
        denom = 1.0 - skew * sharpe_period + ((kurtosis - 1.0) / 4.0) * sharpe_period**2
        sharpe_variance_across_trials = max(denom, 1e-12) / (n_obs - 1)

    benchmark = expected_max_sharpe_under_trials(n_trials, sharpe_variance_across_trials)
    psr_zero = probabilistic_sharpe_ratio(sharpe_period, 0.0, n_obs, skew, kurtosis)
    dsr = probabilistic_sharpe_ratio(sharpe_period, benchmark, n_obs, skew, kurtosis)

    notes = ""
    if n_trials > 1 and sharpe_period <= benchmark:
        notes = (
            f"Observed per-period Sharpe ({sharpe_period:.3f}) does not even exceed the Sharpe "
            f"({benchmark:.3f}) expected from the best of {n_trials} trials under pure luck -- "
            "this result does not clear the multiple-testing bar regardless of PSR(0)."
        )

    return DeflatedSharpeAssessment(
        n_obs=n_obs,
        n_trials=n_trials,
        sharpe_ratio_period=sharpe_period,
        skewness=skew,
        kurtosis=kurtosis,
        expected_max_sharpe_under_null_period=benchmark,
        probabilistic_sharpe_ratio=psr_zero,
        deflated_sharpe_ratio=dsr,
        notes=notes,
    )
