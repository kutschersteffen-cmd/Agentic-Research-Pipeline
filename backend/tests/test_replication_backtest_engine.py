from dataclasses import replace

import pytest

from arp.replication.backtest_engine import run_backtest
from arp.replication.characteristics_data import CharacteristicPanel
from arp.replication.price_data import PricePanel
from arp.schemas.strategy_replication import RebalanceFrequency, SignalType, StrategySpec, WeightingScheme


def _spec(**overrides) -> StrategySpec:
    defaults = dict(
        paper_citation="Test (2020)",
        paper_title="Test paper",
        strategy_name="test momentum",
        signal_type=SignalType.MOMENTUM,
        universe_description="synthetic",
        formation_period_months=3,
        skip_month=False,
        holding_period_months=3,
        rebalance_frequency=RebalanceFrequency.MONTHLY,
        num_portfolios=2,
        long_leg_portfolio=1,
        short_leg_portfolio=2,
        weighting=WeightingScheme.EQUAL,
        sample_period_start="2000-01-01",
        sample_period_end="2001-12-01",
    )
    defaults.update(overrides)
    return StrategySpec(**defaults)


def _persistent_panel(n_months: int = 24) -> PricePanel:
    """Two tickers that always beat the market, two that always lag it --
    a deliberately unambiguous momentum effect, so the long-short return
    should equal the return spread between the two groups every period.
    """
    period_ends = []
    year, month = 2000, 1
    for _ in range(n_months):
        period_ends.append(f"{year}-{month:02d}-01")
        month += 1
        if month > 12:
            month = 1
            year += 1
    returns = {
        "WIN1": [None] + [0.02] * (n_months - 1),
        "WIN2": [None] + [0.025] * (n_months - 1),
        "LOSE1": [None] + [-0.01] * (n_months - 1),
        "LOSE2": [None] + [-0.015] * (n_months - 1),
    }
    return PricePanel(period_ends=period_ends, returns=returns, source="test")


def test_persistent_winners_and_losers_produce_expected_long_short_spread():
    spec = _spec(sample_period_start="2000-01-01", sample_period_end="2001-12-01")
    panel = _persistent_panel()
    result = run_backtest(spec, panel, period_label="in_sample", period_start="2000-01-01", period_end="2001-12-01")

    assert len(result.periods) > 0
    for p in result.periods:
        assert p.long_return_pct == pytest.approx(2.25, abs=1e-9)  # avg of 2.0% and 2.5%
        assert p.short_return_pct == pytest.approx(-1.25, abs=1e-9)  # avg of -1.0% and -1.5%
        assert p.long_short_return_pct == pytest.approx(3.5, abs=1e-9)
    assert result.long_short.annualized_return_pct > 0
    assert result.universe_size == 4


def test_period_window_filters_output_but_keeps_lookback():
    spec = _spec()
    panel = _persistent_panel()
    full = run_backtest(spec, panel, period_label="in_sample", period_start="2000-01-01", period_end="2001-12-01")
    later_start = panel.period_ends[10]
    windowed = run_backtest(spec, panel, period_label="out_of_sample", period_start=later_start, period_end="2001-12-01")
    assert all(p.period_end >= later_start for p in windowed.periods)
    assert len(windowed.periods) < len(full.periods)


def test_non_monthly_rebalance_not_implemented():
    spec = _spec(rebalance_frequency=RebalanceFrequency.QUARTERLY)
    panel = _persistent_panel()
    with pytest.raises(NotImplementedError):
        run_backtest(spec, panel, period_label="in_sample", period_start="2000-01-01", period_end="2001-12-01")


def test_non_equal_weighting_not_implemented():
    spec = _spec(weighting=WeightingScheme.VALUE)
    panel = _persistent_panel()
    with pytest.raises(NotImplementedError):
        run_backtest(spec, panel, period_label="in_sample", period_start="2000-01-01", period_end="2001-12-01")


def test_thin_universe_warns_and_skips_formation():
    spec = _spec(num_portfolios=10)  # only 4 tickers available, need 10
    panel = _persistent_panel()
    result = run_backtest(spec, panel, period_label="in_sample", period_start="2000-01-01", period_end="2001-12-01")
    assert result.periods == []
    assert any("fewer than 10" in w for w in result.warnings)


def _characteristics_reversed(period_ends: list[str]) -> CharacteristicPanel:
    """High characteristic value assigned to the *return-losers*, low to
    the return-winners -- deliberately anti-correlated with returns, so a
    correct value-based selection produces the opposite long/short sign
    from what a (buggy) momentum-based selection would, proving the engine
    actually dispatched to the characteristic rather than price history.
    """
    n = len(period_ends)
    return CharacteristicPanel(
        period_ends=period_ends,
        values={"WIN1": [0.5] * n, "WIN2": [0.4] * n, "LOSE1": [2.0] * n, "LOSE2": [1.9] * n},
        source="test",
    )


def test_value_strategy_ranks_on_characteristic_not_on_returns():
    spec = _spec(signal_type=SignalType.VALUE, formation_period_months=0, characteristic_name="book_to_market", characteristic_lag_months=0)
    panel = _persistent_panel()
    chars = _characteristics_reversed(panel.period_ends)
    result = run_backtest(
        spec, panel, period_label="in_sample", period_start="2000-01-01", period_end="2001-12-01", characteristics=chars
    )
    assert len(result.periods) > 0
    for p in result.periods:
        # Long leg is now LOSE1/LOSE2 (high characteristic), short leg is WIN1/WIN2 (low characteristic) --
        # the opposite sign from the momentum test above, confirming the ranking used the characteristic.
        assert p.long_return_pct == pytest.approx(-1.25, abs=1e-9)
        assert p.short_return_pct == pytest.approx(2.25, abs=1e-9)
        assert p.long_short_return_pct == pytest.approx(-3.5, abs=1e-9)


def test_value_strategy_requires_characteristics_panel():
    spec = _spec(signal_type=SignalType.VALUE, formation_period_months=0)
    panel = _persistent_panel()
    with pytest.raises(ValueError, match="characteristics"):
        run_backtest(spec, panel, period_label="in_sample", period_start="2000-01-01", period_end="2001-12-01")


def test_value_strategy_rejects_misaligned_characteristics_panel():
    spec = _spec(signal_type=SignalType.VALUE, formation_period_months=0)
    panel = _persistent_panel()
    chars = _characteristics_reversed(panel.period_ends)
    misaligned = replace(chars, period_ends=chars.period_ends[:-1])
    with pytest.raises(ValueError, match="period_ends"):
        run_backtest(
            spec,
            panel,
            period_label="in_sample",
            period_start="2000-01-01",
            period_end="2001-12-01",
            characteristics=misaligned,
        )
