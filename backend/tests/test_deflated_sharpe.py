import math

import pytest

from arp.replication.deflated_sharpe import (
    _norm_cdf,
    _norm_ppf,
    _skew_kurtosis,
    deflated_sharpe_ratio,
    expected_max_sharpe_under_trials,
    probabilistic_sharpe_ratio,
)


def test_norm_cdf_and_ppf_are_inverses():
    for p in (0.001, 0.05, 0.25, 0.5, 0.75, 0.95, 0.999):
        assert _norm_cdf(_norm_ppf(p)) == pytest.approx(p, abs=1e-6)


def test_norm_cdf_standard_values():
    assert _norm_cdf(0.0) == pytest.approx(0.5, abs=1e-9)
    assert _norm_cdf(1.959964) == pytest.approx(0.975, abs=1e-4)


def test_norm_ppf_rejects_out_of_range_probability():
    with pytest.raises(ValueError):
        _norm_ppf(0.0)
    with pytest.raises(ValueError):
        _norm_ppf(1.0)


def test_skew_kurtosis_normal_like_series_close_to_gaussian_moments():
    import random

    random.seed(0)
    import numpy as np

    returns = np.asarray([random.gauss(0.0, 1.0) for _ in range(5000)])
    skew, kurt = _skew_kurtosis(returns)
    assert skew == pytest.approx(0.0, abs=0.1)
    assert kurt == pytest.approx(3.0, abs=0.3)


def test_skew_kurtosis_falls_back_on_zero_dispersion():
    import numpy as np

    skew, kurt = _skew_kurtosis(np.asarray([1.0, 1.0, 1.0, 1.0]))
    assert (skew, kurt) == (0.0, 3.0)


def test_probabilistic_sharpe_ratio_higher_for_larger_observed_sharpe():
    low = probabilistic_sharpe_ratio(0.05, 0.0, n_obs=60, skew=0.0, kurtosis=3.0)
    high = probabilistic_sharpe_ratio(0.30, 0.0, n_obs=60, skew=0.0, kurtosis=3.0)
    assert 0.0 <= low <= 1.0
    assert 0.0 <= high <= 1.0
    assert high > low


def test_probabilistic_sharpe_ratio_lower_with_negative_skew_and_fat_tails():
    normal_moments = probabilistic_sharpe_ratio(0.2, 0.0, n_obs=60, skew=0.0, kurtosis=3.0)
    fat_tailed = probabilistic_sharpe_ratio(0.2, 0.0, n_obs=60, skew=-1.5, kurtosis=8.0)
    assert fat_tailed < normal_moments


def test_expected_max_sharpe_zero_for_a_single_trial():
    assert expected_max_sharpe_under_trials(1, sharpe_variance_across_trials=0.05) == 0.0


def test_expected_max_sharpe_increases_with_more_trials():
    small = expected_max_sharpe_under_trials(5, sharpe_variance_across_trials=0.05)
    large = expected_max_sharpe_under_trials(500, sharpe_variance_across_trials=0.05)
    assert large > small > 0.0


def test_expected_max_sharpe_rejects_zero_trials():
    with pytest.raises(ValueError):
        expected_max_sharpe_under_trials(0, sharpe_variance_across_trials=0.05)


def test_deflated_sharpe_ratio_equals_psr_zero_for_a_single_trial():
    returns = [1.0, 0.5, 1.2, -0.3, 0.8, 1.5, 0.2, 0.9, 1.1, -0.1, 0.6, 1.0] * 3
    result = deflated_sharpe_ratio(returns, n_trials=1)
    assert result.expected_max_sharpe_under_null_period == 0.0
    assert result.deflated_sharpe_ratio == pytest.approx(result.probabilistic_sharpe_ratio, abs=1e-9)


def test_deflated_sharpe_ratio_is_more_conservative_with_more_trials():
    returns = [1.0, 0.5, 1.2, -0.3, 0.8, 1.5, 0.2, 0.9, 1.1, -0.1, 0.6, 1.0] * 3
    one_trial = deflated_sharpe_ratio(returns, n_trials=1)
    many_trials = deflated_sharpe_ratio(returns, n_trials=200)
    assert many_trials.deflated_sharpe_ratio < one_trial.deflated_sharpe_ratio


def test_deflated_sharpe_ratio_handles_too_few_observations():
    result = deflated_sharpe_ratio([1.0], n_trials=1)
    assert result.sharpe_ratio_period is None
    assert result.deflated_sharpe_ratio is None
    assert "Fewer than 2" in result.notes


def test_deflated_sharpe_ratio_handles_zero_volatility():
    result = deflated_sharpe_ratio([1.0, 1.0, 1.0, 1.0], n_trials=1)
    assert result.sharpe_ratio_period is None
    assert result.deflated_sharpe_ratio is None
    assert "Zero return volatility" in result.notes


def test_deflated_sharpe_ratio_rejects_zero_trials():
    with pytest.raises(ValueError):
        deflated_sharpe_ratio([1.0, 2.0, 3.0], n_trials=0)
