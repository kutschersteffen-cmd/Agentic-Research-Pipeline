from __future__ import annotations

import pytest

from arp.replication.backtest_engine import run_backtest
from arp.replication.price_data import PricePanel
from arp.schemas.strategy_replication import RebalanceFrequency, SignalType, StrategySpec, WeightingScheme


def _panel() -> PricePanel:
    n = 14
    ends = [f"{2000 + i // 12}-{i % 12 + 1:02d}-01" for i in range(n)]
    returns = {
        "W1": [None] + [0.02 + 0.001 * (i % 3) for i in range(1, n)],
        "W2": [None] + [0.025] * (n - 1),
        "L1": [None] + [-0.01 - 0.001 * (i % 2) for i in range(1, n)],
        "L2": [None] + [-0.015] * (n - 1),
    }
    return PricePanel(ends, returns, "test")


def _spec(holding: int) -> StrategySpec:
    return StrategySpec(
        paper_citation="Test (2020)",
        paper_title="Test paper",
        strategy_name="test momentum",
        signal_type=SignalType.MOMENTUM,
        universe_description="synthetic",
        formation_period_months=3,
        holding_period_months=holding,
        rebalance_frequency=RebalanceFrequency.CUSTOM,
        rebalance_interval_months=1,
        num_portfolios=2,
        long_leg_portfolio=1,
        short_leg_portfolio=2,
        weighting=WeightingScheme.EQUAL,
        sample_period_start="2000-01-01",
        sample_period_end="2001-12-01",
    )


def _run(holding: int, **kw):
    return run_backtest(_spec(holding), _panel(), period_label="in_sample", period_start="2000-01-01", period_end="2001-12-01", **kw)


# Gross figures recorded from the engine before cost support was added.
@pytest.mark.parametrize(
    ("holding", "avg_num"),
    [(1, 2.0), (3, 5.4)],
)
def test_zero_cost_leaves_results_unchanged(holding, avg_num):
    result = _run(holding, cost_bps=0.0)
    assert result.net_long_short is None
    assert len(result.periods) == 10
    assert result.long_short.monthly_mean_return_pct == pytest.approx(3.575)
    assert result.long_leg.monthly_mean_return_pct == pytest.approx(2.3)
    assert result.short_leg.monthly_mean_return_pct == pytest.approx(-1.275)
    assert result.avg_num_long == pytest.approx(avg_num)
    assert result.avg_num_short == pytest.approx(avg_num)
    assert result.periods[0].long_short_return_pct == pytest.approx(3.55)
    assert all(w is not None for w in (p.traded_weight for p in result.periods))


def test_net_equals_gross_minus_cost():
    gross = _run(3)
    net = _run(3, cost_bps=10)
    assert net.net_long_short is not None
    assert [p.traded_weight for p in net.periods] == [p.traded_weight for p in gross.periods]
    net_series = [p.long_short_return_pct - 10 / 10000 * p.traded_weight * 100 for p in net.periods]
    assert net.net_long_short.monthly_mean_return_pct == pytest.approx(sum(net_series) / len(net_series))
    assert net.long_short == gross.long_short


def test_constant_portfolio_has_zero_turnover_after_first_month():
    result = _run(1)
    weights = [p.traded_weight for p in result.periods]
    assert weights[0] == pytest.approx(2.0)
    assert weights[1:] == [0.0] * (len(weights) - 1)
    assert result.monthly_turnover_pct == pytest.approx(2.0 / len(weights) / 2 * 100)
    assert 0 < result.monthly_turnover_pct < 20


def test_cost_reduces_net_return():
    result = _run(3, cost_bps=10)
    assert result.net_long_short.monthly_mean_return_pct < result.long_short.monthly_mean_return_pct
