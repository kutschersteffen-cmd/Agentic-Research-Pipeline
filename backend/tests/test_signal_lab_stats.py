from __future__ import annotations

import numpy as np
import pytest

from arp.replication.characteristics_data import CharacteristicPanel
from arp.replication.price_data import PricePanel
from arp.signal_lab.stats import (
    compare_signals,
    mean_cross_correlation,
    newey_west_t,
    rank_ic_series,
    spearman,
    summarize_ic,
)

DATES = ["2020-01-31", "2020-02-29", "2020-03-31", "2020-04-30"]
TICKERS = [f"T{i}" for i in range(12)]


def _prices(rows: list[list[float | None]]) -> PricePanel:
    # rows[month][ticker]
    return PricePanel(
        period_ends=DATES,
        returns={t: [rows[m][k] for m in range(4)] for k, t in enumerate(TICKERS)},
        source="test",
    )


def _scores(rows: list[list[float | None]]) -> CharacteristicPanel:
    return CharacteristicPanel(
        period_ends=DATES,
        values={t: [rows[m][k] for m in range(4)] for k, t in enumerate(TICKERS)},
        source="test",
    )


def test_spearman_perfect_and_inverse():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)
    assert 0 < spearman([1, 1, 2, 3], [1, 2, 3, 4]) < 1


def test_spearman_constant_is_none():
    assert spearman([1, 1, 1, 1], [1, 2, 3, 4]) is None
    assert spearman([1, 2, 3, 4], [5, 5, 5, 5]) is None
    assert spearman([1, 2], [1, 2]) is None


def test_rank_ic_skips_thin_and_constant_months():
    rets = [[None] * 12] + [[float(k) for k in range(12)] for _ in range(3)]
    base = [float(k) for k in range(12)]
    scores = [
        base,  # paired with month 1: fine
        [v if k < 5 else None for k, v in enumerate(base)],  # only 5 names
        [1.0] * 12,  # constant
        base,  # no forward month
    ]
    out = rank_ic_series(_scores(scores), _prices(rets))
    assert [d for d, _ in out] == [DATES[0]]


def test_rank_ic_uses_forward_return():
    scores = [[float(k * (m + 1) % 7) + k * 0.01 for k in range(12)] for m in range(4)]
    rets = [[None] * 12] + [list(scores[m - 1]) for m in range(1, 4)]
    out = rank_ic_series(_scores(scores), _prices(rets))
    assert [d for d, _ in out] == DATES[:3]
    assert all(ic == pytest.approx(1.0) for _, ic in out)


def test_newey_west_matches_plain_t_for_iid():
    x = np.random.default_rng(0).normal(0.1, 1, 400)
    plain_t = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
    assert abs(newey_west_t(list(x)) - plain_t) < 0.3


def test_newey_west_lower_for_autocorrelated():
    e = np.random.default_rng(0).normal(0, 1, 400)
    x = np.zeros(400)
    for i in range(1, 400):
        x[i] = 0.7 * x[i - 1] + e[i]
    x += 0.2
    plain_t = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
    assert abs(newey_west_t(list(x))) < abs(plain_t)


def test_newey_west_too_short_or_constant_is_none():
    assert newey_west_t([0.1, 0.2]) is None
    assert newey_west_t([0.1] * 10) is None


def test_summarize_ic_hit_rate():
    s = summarize_ic([("a", 0.1), ("b", -0.05), ("c", 0.2)])
    assert s.n == 3
    assert s.hit_rate == pytest.approx(2 / 3)
    assert s.mean == pytest.approx(0.25 / 3)


def test_summarize_ic_empty():
    s = summarize_ic([])
    assert (s.n, s.mean, s.t_nw, s.hit_rate) == (0, None, None, None)


def _identity_case():
    scores = [[float(k) for k in range(12)] for _ in range(4)]
    rets = [[None] * 12] + [[float(k) for k in range(12)] for _ in range(3)]
    return _scores(scores), _prices(rets)


def test_rank_ic_rejects_mismatched_grids():
    s, p = _identity_case()
    p.period_ends = DATES[1:]
    with pytest.raises(ValueError, match="4 vs 3"):
        rank_ic_series(s, p)


@pytest.mark.parametrize("fm", [0, -1])
def test_rank_ic_rejects_non_forward_months(fm):
    s, p = _identity_case()
    with pytest.raises(ValueError, match="forward_months"):
        rank_ic_series(s, p, forward_months=fm)


def test_rank_ic_treats_nan_as_missing():
    s, p = _identity_case()
    nan = float("nan")
    for t in TICKERS[:3]:
        s.values[t][0] = nan  # 9 names left in month 0 -> skipped
    p.returns["T11"][2] = nan  # 11 names left in month 1 -> still scored
    out = rank_ic_series(s, p)
    assert [d for d, _ in out] == DATES[1:3]
    assert all(ic == pytest.approx(1.0) for _, ic in out)


def test_rank_ic_forward_months_two_and_short_ticker_list():
    scores = [[float(k) for k in range(12)] for _ in range(4)]
    rets = [[None] * 12, [None] * 12] + [[float(k) for k in range(12)] for _ in range(2)]
    s, p = _scores(scores), _prices(rets)
    out = rank_ic_series(s, p, forward_months=2)
    assert [d for d, _ in out] == DATES[:2]
    p.returns["T0"] = p.returns["T0"][:2]  # shorter than period_ends: skipped for that month, no IndexError
    assert [d for d, _ in rank_ic_series(s, p, forward_months=2, min_names=12)] == []


def test_cross_correlation_identical_panels_is_one():
    rng = np.random.default_rng(0)
    p = _scores([list(rng.normal(size=12)) for _ in range(4)])
    assert mean_cross_correlation(p, p) == pytest.approx(1.0)


def test_cross_correlation_mismatched_grids_raises():
    a = _scores([[float(k) for k in range(12)]] * 4)
    b = CharacteristicPanel(period_ends=DATES[:3], values={t: v[:3] for t, v in a.values.items()}, source="test")
    with pytest.raises(ValueError):
        mean_cross_correlation(a, b)


def _noise(seed: int, n: int = 60) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.0, 0.5, n)


def test_compare_clear_difference():
    a = (1.0 + _noise(1)).tolist()
    b = (0.0 + _noise(2)).tolist()
    assert compare_signals(a, b, n_comparisons=1) == "a_higher"


def test_compare_indistinguishable_is_insufficient():
    assert compare_signals(_noise(1).tolist(), _noise(2).tolist(), n_comparisons=1) == "insufficient_data"


def test_compare_too_few_periods():
    assert compare_signals([5.0] * 6, [0.0] * 6, n_comparisons=1) == "insufficient_data"


def test_compare_length_mismatch_raises():
    with pytest.raises(ValueError):
        compare_signals([1.0] * 12, [1.0] * 13, n_comparisons=1)


EFFECT = 0.25


def test_compare_more_comparisons_is_harder():
    a = (EFFECT + _noise(1)).tolist()
    b = _noise(2).tolist()
    assert compare_signals(a, b, n_comparisons=1) == "a_higher"
    assert compare_signals(a, b, n_comparisons=50) == "insufficient_data"
