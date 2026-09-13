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


def _monthly_dates(n_months: int) -> list[str]:
    dates = []
    year, month = 2000, 1
    for _ in range(n_months):
        dates.append(f"{year}-{month:02d}-01")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return dates


def _alternating_fixture(n_months: int = 13, block: int = 1) -> tuple[PricePanel, CharacteristicPanel]:
    """Ticker A always realizes +5%/month, ticker B always -3%/month (fixed,
    never alternating) -- but which of them is "high characteristic" flips
    every `block` formation months. So whichever one of {5.0, -3.0} a given
    output period's long_return_pct shows is entirely a function of which
    ticker the *selection* picked that period, not of the realized return
    itself -- letting rebalance-frequency tests below assert on selection
    stability/instability directly through the public BacktestResult.

    `block` must not equal (or evenly divide/be divided by, in a way that
    always lands on the same phase) the rebalance interval under test, or
    every actual rebalance date will coincidentally sample the same phase
    and the test will show no alternation at all regardless of whether the
    engine is behaving correctly -- callers choose `block` accordingly.
    """
    period_ends = _monthly_dates(n_months)
    returns = {"A": [None] + [0.05] * (n_months - 1), "B": [None] + [-0.03] * (n_months - 1)}
    panel = PricePanel(period_ends=period_ends, returns=returns, source="test")
    chars = CharacteristicPanel(
        period_ends=period_ends,
        values={
            "A": [2.0 if (f // block) % 2 == 0 else 0.5 for f in range(n_months)],
            "B": [0.5 if (f // block) % 2 == 0 else 2.0 for f in range(n_months)],
        },
        source="test",
    )
    return panel, chars


def _value_spec(**overrides) -> StrategySpec:
    defaults = dict(
        paper_citation="Test (2020)",
        paper_title="Test value paper",
        strategy_name="test value",
        signal_type=SignalType.VALUE,
        universe_description="synthetic",
        formation_period_months=0,
        holding_period_months=1,
        rebalance_frequency=RebalanceFrequency.MONTHLY,
        num_portfolios=2,
        long_leg_portfolio=1,
        short_leg_portfolio=2,
        weighting=WeightingScheme.EQUAL,
        characteristic_name="test_char",
        characteristic_lag_months=0,
        sample_period_start="2000-01-01",
        sample_period_end="2001-12-01",
    )
    defaults.update(overrides)
    return StrategySpec(**defaults)


def test_monthly_rebalance_flips_selection_every_period():
    panel, chars = _alternating_fixture(13)
    spec = _value_spec(holding_period_months=1, rebalance_frequency=RebalanceFrequency.MONTHLY)
    result = run_backtest(
        spec, panel, period_label="in_sample", period_start=panel.period_ends[0], period_end=panel.period_ends[-1], characteristics=chars
    )
    long_returns = [p.long_return_pct for p in result.periods]
    assert long_returns == pytest.approx([5.0, -3.0] * 6)  # 12 output periods (m=1..12), strictly alternating


def test_quarterly_rebalance_holds_the_same_selection_for_a_full_quarter():
    panel, chars = _alternating_fixture(13)
    spec = _value_spec(holding_period_months=3, rebalance_frequency=RebalanceFrequency.QUARTERLY)
    result = run_backtest(
        spec, panel, period_label="in_sample", period_start=panel.period_ends[0], period_end=panel.period_ends[-1], characteristics=chars
    )
    long_returns = [p.long_return_pct for p in result.periods]
    # Same alternating characteristic as the monthly test above, but a 3-month rebalance interval matched to a
    # 3-month holding period means exactly one active cohort at a time -- the selection made at each quarter's
    # single formation date is held fixed for all 3 months of that quarter, instead of flipping every period.
    assert long_returns == pytest.approx([5.0, 5.0, 5.0, -3.0, -3.0, -3.0, 5.0, 5.0, 5.0, -3.0, -3.0, -3.0])


def test_custom_rebalance_interval_is_honored():
    # block=2: the characteristic's phase changes every 2 formation months, distinct from the interval=2
    # rebalance schedule under test -- see _alternating_fixture's own docstring on why the two must differ.
    panel, chars = _alternating_fixture(13, block=2)
    spec = _value_spec(
        holding_period_months=2, rebalance_frequency=RebalanceFrequency.CUSTOM, rebalance_interval_months=2
    )
    result = run_backtest(
        spec, panel, period_label="in_sample", period_start=panel.period_ends[0], period_end=panel.period_ends[-1], characteristics=chars
    )
    long_returns = [p.long_return_pct for p in result.periods]
    assert long_returns == pytest.approx([5.0, 5.0, -3.0, -3.0, 5.0, 5.0, -3.0, -3.0, 5.0, 5.0, -3.0, -3.0])


def test_custom_rebalance_without_interval_months_raises():
    panel, chars = _alternating_fixture(13)
    spec = _value_spec(rebalance_frequency=RebalanceFrequency.CUSTOM)  # rebalance_interval_months left unset
    with pytest.raises(ValueError, match="CUSTOM"):
        run_backtest(
            spec, panel, period_label="in_sample", period_start=panel.period_ends[0], period_end=panel.period_ends[-1], characteristics=chars
        )


def test_annual_rebalance_with_anchor_month_forms_a_cohort_only_in_june():
    panel_dates = _monthly_dates(37)  # 2000-01 .. 2003-01
    returns = {"A": [None] + [0.05] * 36, "B": [None] + [-0.03] * 36}
    panel = PricePanel(period_ends=panel_dates, returns=returns, source="test")
    chars = CharacteristicPanel(period_ends=panel_dates, values={"A": [2.0] * 37, "B": [0.5] * 37}, source="test")
    spec = _value_spec(
        holding_period_months=12,
        rebalance_frequency=RebalanceFrequency.ANNUAL,
        rebalance_anchor_month=6,
        sample_period_start=panel_dates[0],
        sample_period_end=panel_dates[-1],
    )
    result = run_backtest(
        spec, panel, period_label="in_sample", period_start=panel_dates[0], period_end=panel_dates[-1], characteristics=chars
    )
    assert len(result.periods) > 0
    assert all(p.long_return_pct == pytest.approx(5.0) for p in result.periods)
    # The first June in the panel is index 5 (2000-06-01); with holding_period_months=12 the first output
    # period is the month right after that formation.
    assert result.periods[0].period_end == panel_dates[6]


def test_rebalance_anchor_month_never_occurring_warns_and_produces_no_periods():
    panel_dates = _monthly_dates(3)  # Jan-Mar 2000 only -- June never occurs
    returns = {"A": [None, 0.05, 0.05], "B": [None, -0.03, -0.03]}
    panel = PricePanel(period_ends=panel_dates, returns=returns, source="test")
    chars = CharacteristicPanel(period_ends=panel_dates, values={"A": [2.0] * 3, "B": [0.5] * 3}, source="test")
    spec = _value_spec(
        holding_period_months=12,
        rebalance_frequency=RebalanceFrequency.ANNUAL,
        rebalance_anchor_month=6,
        sample_period_start=panel_dates[0],
        sample_period_end=panel_dates[-1],
    )
    result = run_backtest(
        spec, panel, period_label="in_sample", period_start=panel_dates[0], period_end=panel_dates[-1], characteristics=chars
    )
    assert result.periods == []
    assert any("never occurs" in w for w in result.warnings)
