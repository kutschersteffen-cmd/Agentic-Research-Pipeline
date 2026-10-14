from __future__ import annotations

import numpy as np
import pytest

from arp.replication.characteristics_data import CharacteristicPanel
from arp.replication.price_data import PricePanel
from arp.signal_lab.stats import newey_west_t, rank_ic_series, spearman, summarize_ic

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
