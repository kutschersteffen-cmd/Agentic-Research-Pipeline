"""Statistical primitives checked against hand-computed values."""

from __future__ import annotations

import math

import pytest

from arp.decarb import stats


def test_pearson_perfect_and_constant():
    assert stats.pearson([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)
    assert stats.pearson([1, 2, 3, 4], [8, 6, 4, 2]) == pytest.approx(-1.0)
    # A constant series carries no information; convention is 0, not nan.
    assert stats.pearson([1, 1, 1, 1], [1, 2, 3, 4]) == 0.0


def test_rank_averages_ties():
    assert stats.rank([10, 20, 20, 30]) == [1.0, 2.5, 2.5, 4.0]


def test_spearman_monotone_but_not_linear():
    # Perfectly monotone, wildly non-linear: Spearman 1, Pearson well below.
    xs = [1, 2, 3, 4, 5]
    ys = [1, 4, 9, 100, 10000]
    assert stats.spearman(xs, ys) == pytest.approx(1.0)
    assert stats.pearson(xs, ys) < 0.85


def test_phi_coefficient_known_values():
    a = [True, True, False, False]
    b = [True, True, False, False]
    assert stats.phi_coefficient(a, b) == pytest.approx(1.0)
    assert stats.phi_coefficient(a, [False, False, True, True]) == pytest.approx(-1.0)
    # Independent: 2x2 table with all cells equal.
    assert stats.phi_coefficient([True, True, False, False], [True, False, True, False]) == pytest.approx(0.0)


def test_auc_ordering_and_ties():
    assert stats.auc([1.0, 0.0], [True, False]) == pytest.approx(1.0)
    assert stats.auc([0.0, 1.0], [True, False]) == pytest.approx(0.0)
    # All scores tied -> no discrimination.
    assert stats.auc([0.5, 0.5, 0.5, 0.5], [True, False, True, False]) == pytest.approx(0.5)
    # Single class -> undefined, reported as 0.5.
    assert stats.auc([0.9, 0.1], [True, True]) == pytest.approx(0.5)


def test_ols_recovers_known_coefficients():
    # y = 3 + 2*x1 - 1*x2 exactly.
    x = [[1.0, 0.0], [2.0, 1.0], [3.0, 2.0], [4.0, 0.0], [5.0, 3.0], [6.0, 1.0]]
    y = [3 + 2 * a - b for a, b in x]
    fit = stats.ols(x, y)
    assert fit.coefficients[0] == pytest.approx(3.0, abs=1e-4)
    assert fit.coefficients[1] == pytest.approx(2.0, abs=1e-4)
    assert fit.coefficients[2] == pytest.approx(-1.0, abs=1e-4)
    assert fit.r_squared == pytest.approx(1.0, abs=1e-6)


def test_ols_rejects_underdetermined_system():
    with pytest.raises(ValueError, match="more observations"):
        stats.ols([[1.0, 2.0]], [1.0])


def test_logistic_regression_separates_a_clean_boundary():
    x = [[v] for v in (-4, -3, -2, -1, 1, 2, 3, 4)]
    y = [v[0] > 0 for v in x]
    beta = stats.logistic_regression(x, y)
    assert beta[1] > 0  # positive slope on a positively-separating feature


def test_log_mean_identity_and_symmetry():
    assert stats.log_mean(5.0, 5.0) == pytest.approx(5.0)
    assert stats.log_mean(1.0, 3.0) == pytest.approx(stats.log_mean(3.0, 1.0))
    # Lies strictly between the arguments.
    assert 1.0 < stats.log_mean(1.0, 3.0) < 3.0
    with pytest.raises(ValueError):
        stats.log_mean(0.0, 1.0)


def test_winsorise_clips_tails():
    xs = [-1000.0] + [1.0] * 20 + [1000.0]
    out = stats.winsorise(xs, lower=0.05, upper=0.95)
    assert max(out) < 1000.0
    assert min(out) > -1000.0
