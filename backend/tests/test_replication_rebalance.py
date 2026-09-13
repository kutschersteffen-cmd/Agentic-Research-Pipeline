import pytest

from arp.replication.rebalance import resolve_rebalance_interval_months, resolve_rebalance_months
from arp.schemas.strategy_replication import RebalanceFrequency, SignalType, StrategySpec


def _spec(**overrides) -> StrategySpec:
    defaults = dict(
        paper_citation="Test (2020)",
        paper_title="Test paper",
        strategy_name="test",
        signal_type=SignalType.MOMENTUM,
        universe_description="synthetic",
        formation_period_months=3,
        holding_period_months=3,
        short_leg_portfolio=2,
        sample_period_start="2000-01-01",
        sample_period_end="2001-12-01",
    )
    defaults.update(overrides)
    return StrategySpec(**defaults)


def test_resolve_interval_for_fixed_frequencies():
    assert resolve_rebalance_interval_months(_spec(rebalance_frequency=RebalanceFrequency.MONTHLY)) == 1
    assert resolve_rebalance_interval_months(_spec(rebalance_frequency=RebalanceFrequency.QUARTERLY)) == 3
    assert resolve_rebalance_interval_months(_spec(rebalance_frequency=RebalanceFrequency.ANNUAL)) == 12


def test_resolve_interval_for_custom():
    spec = _spec(rebalance_frequency=RebalanceFrequency.CUSTOM, rebalance_interval_months=7)
    assert resolve_rebalance_interval_months(spec) == 7


def test_resolve_interval_custom_without_value_raises():
    spec = _spec(rebalance_frequency=RebalanceFrequency.CUSTOM)
    with pytest.raises(ValueError, match="CUSTOM"):
        resolve_rebalance_interval_months(spec)


def test_resolve_interval_custom_ignores_fixed_frequency_field_value():
    # rebalance_interval_months is only consulted for CUSTOM -- setting it alongside MONTHLY is a no-op.
    spec = _spec(rebalance_frequency=RebalanceFrequency.MONTHLY, rebalance_interval_months=99)
    assert resolve_rebalance_interval_months(spec) == 1


def test_resolve_months_no_anchor_starts_at_index_zero():
    period_ends = [f"2000-{m:02d}-01" for m in range(1, 13)]  # Jan..Dec 2000
    assert resolve_rebalance_months(period_ends, interval_months=3, anchor_month=None) == {0, 3, 6, 9}


def test_resolve_months_interval_one_ignores_anchor():
    period_ends = [f"2000-{m:02d}-01" for m in range(1, 5)]
    assert resolve_rebalance_months(period_ends, interval_months=1, anchor_month=6) == {0, 1, 2, 3}


def test_resolve_months_annual_anchor_reproduces_june_rebalance():
    # Two full years, monthly grid -- June (month 6) is index 5 and index 17.
    period_ends = [f"{y}-{m:02d}-01" for y in (2000, 2001) for m in range(1, 13)]
    months = resolve_rebalance_months(period_ends, interval_months=12, anchor_month=6)
    assert months == {5, 17}


def test_resolve_months_quarterly_anchor_picks_every_third_month_from_anchor():
    period_ends = [f"2000-{m:02d}-01" for m in range(1, 13)]  # Jan..Dec
    # anchor_month=2 (Feb, index 1) with interval 3 -> Feb/May/Aug/Nov = indices 1,4,7,10
    months = resolve_rebalance_months(period_ends, interval_months=3, anchor_month=2)
    assert months == {1, 4, 7, 10}


def test_resolve_months_anchor_never_occurring_returns_empty():
    period_ends = [f"2000-{m:02d}-01" for m in range(1, 4)]  # Jan-Mar only
    assert resolve_rebalance_months(period_ends, interval_months=12, anchor_month=6) == set()
