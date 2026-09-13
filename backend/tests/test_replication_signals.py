import pytest

from arp.replication.price_data import PricePanel
from arp.replication.signals import assign_portfolios, momentum_scores


def _panel() -> PricePanel:
    period_ends = [f"2000-{m:02d}-01" for m in range(1, 9)]  # 8 months
    return PricePanel(
        period_ends=period_ends,
        returns={
            "AAA": [None, 0.01, 0.02, 0.03, 0.01, 0.02, 0.01, 0.01],
            "BBB": [None, -0.01, -0.02, -0.01, None, -0.01, -0.02, -0.01],  # a gap at index 4
            "CCC": [None, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        },
        source="test",
    )


def test_momentum_scores_uses_correct_window_and_compounds():
    panel = _panel()
    # formation_idx=5, J=3, no skip -> window is indices [3, 4, 5]
    scores = momentum_scores(panel, formation_idx=5, formation_period_months=3, skip_month=False)
    expected_aaa = (1.03 * 1.01 * 1.02) - 1.0
    assert scores["AAA"] == pytest.approx(expected_aaa)
    assert scores["CCC"] == pytest.approx(0.0)
    # BBB has a None in the window (index 4) and must be excluded entirely.
    assert "BBB" not in scores


def test_momentum_scores_skip_month_shifts_window_back_by_one():
    panel = _panel()
    # formation_idx=5, skip_month -> end=4, window is indices [2, 3, 4]
    scores = momentum_scores(panel, formation_idx=5, formation_period_months=3, skip_month=True)
    expected_aaa = (1.02 * 1.03 * 1.01) - 1.0
    assert scores["AAA"] == pytest.approx(expected_aaa)
    # BBB's window [2,3,4] includes the None at index 4, so still excluded.
    assert "BBB" not in scores


def test_momentum_scores_insufficient_history_returns_empty():
    panel = _panel()
    scores = momentum_scores(panel, formation_idx=1, formation_period_months=6, skip_month=False)
    assert scores == {}


def test_assign_portfolios_ranks_highest_score_as_bucket_one():
    scores = {"A": 0.10, "B": 0.08, "C": 0.06, "D": 0.04, "E": 0.02, "F": 0.0, "G": -0.02, "H": -0.04, "I": -0.06, "J": -0.08}
    buckets = assign_portfolios(scores, num_portfolios=10)
    assert buckets["A"] == 1
    assert buckets["J"] == 10
    # Monotonic: strictly non-decreasing bucket number as score decreases.
    ordered = sorted(scores, key=lambda t: scores[t], reverse=True)
    bucket_sequence = [buckets[t] for t in ordered]
    assert bucket_sequence == sorted(bucket_sequence)


def test_assign_portfolios_splits_unevenly_sized_universe():
    scores = {t: -i for i, t in enumerate("ABCDE")}  # 5 names, 2 buckets
    buckets = assign_portfolios(scores, num_portfolios=2)
    assert set(buckets.values()) == {1, 2}
    assert list(buckets.values()).count(1) + list(buckets.values()).count(2) == 5
