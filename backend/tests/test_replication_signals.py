import pytest

from arp.replication.characteristics_data import CharacteristicPanel
from arp.replication.price_data import PricePanel
from arp.replication.signals import assign_portfolios, compute_signal_scores, momentum_scores, value_scores
from arp.schemas.strategy_replication import RebalanceFrequency, SignalType, StrategySpec, WeightingScheme


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


def _characteristics() -> CharacteristicPanel:
    period_ends = [f"2000-{m:02d}-01" for m in range(1, 9)]
    return CharacteristicPanel(
        period_ends=period_ends,
        values={
            "AAA": [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7],
            "BBB": [0.5, 0.5, None, 0.5, 0.5, 0.5, 0.5, 0.5],  # a gap at index 2
        },
        source="test",
    )


def test_value_scores_reads_the_lagged_characteristic_level():
    chars = _characteristics()
    # formation_idx=5, lag=2 -> reads index 3 directly (no compounding, unlike momentum).
    scores = value_scores(chars, formation_idx=5, characteristic_lag_months=2)
    assert scores["AAA"] == pytest.approx(1.3)
    assert scores["BBB"] == pytest.approx(0.5)


def test_value_scores_excludes_ticker_missing_at_the_lagged_index():
    chars = _characteristics()
    # formation_idx=4, lag=2 -> reads index 2, which is None for BBB.
    scores = value_scores(chars, formation_idx=4, characteristic_lag_months=2)
    assert "AAA" in scores
    assert "BBB" not in scores


def test_value_scores_out_of_range_lag_returns_empty():
    chars = _characteristics()
    assert value_scores(chars, formation_idx=1, characteristic_lag_months=5) == {}
    assert value_scores(chars, formation_idx=10, characteristic_lag_months=0) == {}


def _value_spec(**overrides) -> StrategySpec:
    defaults = dict(
        paper_citation="Test (2020)",
        paper_title="Test value paper",
        strategy_name="test value",
        signal_type=SignalType.VALUE,
        universe_description="synthetic",
        holding_period_months=3,
        rebalance_frequency=RebalanceFrequency.MONTHLY,
        num_portfolios=2,
        long_leg_portfolio=1,
        short_leg_portfolio=2,
        weighting=WeightingScheme.EQUAL,
        characteristic_name="book_to_market",
        characteristic_lag_months=1,
        sample_period_start="2000-01-01",
        sample_period_end="2000-08-01",
    )
    defaults.update(overrides)
    return StrategySpec(**defaults)


def test_compute_signal_scores_dispatches_to_value():
    spec = _value_spec()
    chars = _characteristics()
    panel = PricePanel(period_ends=chars.period_ends, returns={"AAA": [None] * 8, "BBB": [None] * 8}, source="test")
    scores = compute_signal_scores(spec, panel, formation_idx=5, characteristics=chars)
    assert scores == value_scores(chars, formation_idx=5, characteristic_lag_months=1)


def test_compute_signal_scores_value_without_characteristics_raises():
    spec = _value_spec()
    panel = PricePanel(period_ends=[], returns={}, source="test")
    with pytest.raises(ValueError, match="CharacteristicPanel"):
        compute_signal_scores(spec, panel, formation_idx=0, characteristics=None)
