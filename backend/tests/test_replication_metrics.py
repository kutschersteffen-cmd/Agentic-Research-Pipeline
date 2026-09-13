import numpy as np
import pytest

from arp.replication.metrics import compute_leg_performance


def test_empty_series_returns_defaults():
    perf = compute_leg_performance([])
    assert perf.annualized_return_pct is None
    assert perf.sharpe_ratio is None


def test_constant_returns_annualized_via_compounding():
    perf = compute_leg_performance([1.0] * 12)
    expected_annualized = (1.01**12 - 1) * 100
    assert perf.annualized_return_pct == pytest.approx(expected_annualized, rel=1e-9)
    assert perf.monthly_mean_return_pct == pytest.approx(1.0, rel=1e-9)
    # Constant returns have zero volatility -- Sharpe/t-stat are undefined,
    # not silently reported as infinite or zero.
    assert perf.annualized_volatility_pct == pytest.approx(0.0, abs=1e-9)
    assert perf.sharpe_ratio is None
    assert perf.t_stat is None
    # Monotonically increasing equity curve -- no drawdown at all.
    assert perf.max_drawdown_pct == pytest.approx(0.0, abs=1e-9)


def test_max_drawdown_on_losing_streak():
    perf = compute_leg_performance([-10.0, -10.0, -10.0])
    compounded = 0.9 * 0.9 * 0.9
    expected_annualized = (compounded ** (12 / 3) - 1) * 100
    expected_drawdown = (compounded / 0.9 - 1) * 100  # trough vs. the running peak (month 1)
    assert perf.annualized_return_pct == pytest.approx(expected_annualized, rel=1e-9)
    assert perf.max_drawdown_pct == pytest.approx(expected_drawdown, rel=1e-9)


def test_alpha_beta_against_benchmark():
    benchmark = [1.0, 2.0, 3.0, 4.0, 5.0]
    strategy = [2 * b + 0.5 for b in benchmark]
    perf = compute_leg_performance(strategy, benchmark)
    b = np.array(benchmark) / 100.0
    r = np.array(strategy) / 100.0
    slope, intercept = np.polyfit(b, r, 1)
    assert perf.beta == pytest.approx(float(slope), rel=1e-9)
    assert perf.alpha_annualized_pct == pytest.approx(((1 + intercept) ** 12 - 1) * 100, rel=1e-9)


def test_sharpe_and_t_stat_are_finite_for_varying_returns():
    perf = compute_leg_performance([2.0, -1.0, 3.0, 0.5, 1.5, -2.0, 2.0, 1.0, 0.0, 3.0, -1.0, 2.0])
    assert perf.sharpe_ratio is not None
    assert perf.t_stat is not None
    assert perf.annualized_volatility_pct > 0
