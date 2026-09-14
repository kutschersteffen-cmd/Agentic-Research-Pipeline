import random

import pytest

from arp.replication.cpcv import _make_blocks, _purged_embargoed_train_period_ends, run_pbo_analysis
from arp.replication.price_data import PricePanel
from arp.schemas.strategy_replication import RebalanceFrequency, SignalType, StrategySpec


def _spec(spec_id, formation_period_months, sample_start, sample_end) -> StrategySpec:
    return StrategySpec(
        spec_id=spec_id,
        paper_citation="Test (2020)",
        paper_title="Test paper",
        strategy_name="test momentum",
        signal_type=SignalType.MOMENTUM,
        universe_description="synthetic",
        formation_period_months=formation_period_months,
        holding_period_months=3,
        num_portfolios=4,
        long_leg_portfolio=1,
        short_leg_portfolio=4,
        rebalance_frequency=RebalanceFrequency.MONTHLY,
        sample_period_start=sample_start,
        sample_period_end=sample_end,
    )


def _monthly_panel(n_months: int, seed: int) -> PricePanel:
    rng = random.Random(seed)
    period_ends = []
    year, month = 2000, 1
    for _ in range(n_months):
        period_ends.append(f"{year}-{month:02d}-01")
        month += 1
        if month > 12:
            month, year = 1, year + 1
    tickers = [f"T{i}" for i in range(20)]
    returns = {t: [None] + [rng.gauss(0.01, 0.05) for _ in range(n_months - 1)] for t in tickers}
    return PricePanel(period_ends=period_ends, returns=returns, source="test")


def test_make_blocks_splits_evenly_and_covers_every_period():
    period_ends = [f"2000-{m:02d}-01" for m in range(1, 13)]
    blocks = _make_blocks(period_ends, num_blocks=4)
    assert len(blocks) == 4
    assert sum(len(b) for b in blocks) == len(period_ends)
    assert [d for b in blocks for d in b] == period_ends  # contiguous, in order


def test_make_blocks_rejects_odd_or_too_small_num_blocks():
    period_ends = [f"2000-{m:02d}-01" for m in range(1, 13)]
    with pytest.raises(ValueError):
        _make_blocks(period_ends, num_blocks=3)
    with pytest.raises(ValueError):
        _make_blocks(period_ends, num_blocks=1)
    with pytest.raises(ValueError):
        _make_blocks(period_ends, num_blocks=100)


def test_purged_embargoed_train_excludes_test_block_and_buffers():
    period_ends = [f"2000-{m:02d}-01" for m in range(1, 13)]
    blocks = _make_blocks(period_ends, num_blocks=6)  # 2-month blocks
    # Test block index 2 covers months 5-6; purge 1 month before, embargo 1 month after.
    train = _purged_embargoed_train_period_ends(blocks, {2}, purge_months=1, embargo_months=1)
    test_dates = set(blocks[2])
    assert test_dates.isdisjoint(train)
    assert "2000-04-01" not in train  # purged (immediately before the test block)
    assert "2000-07-01" not in train  # embargoed (immediately after the test block)
    assert "2000-01-01" in train  # far from the test block, still eligible


def test_run_pbo_analysis_requires_at_least_two_candidates():
    panel = _monthly_panel(24, seed=1)
    spec = _spec("a", 3, panel.period_ends[0], panel.period_ends[-1])
    with pytest.raises(ValueError):
        run_pbo_analysis([spec], panel, period_start=panel.period_ends[0], period_end=panel.period_ends[-1])


def test_run_pbo_analysis_rejects_duplicate_spec_ids():
    panel = _monthly_panel(24, seed=1)
    a = _spec("a", 3, panel.period_ends[0], panel.period_ends[-1])
    b = _spec("a", 6, panel.period_ends[0], panel.period_ends[-1])
    with pytest.raises(ValueError):
        run_pbo_analysis([a, b], panel, period_start=panel.period_ends[0], period_end=panel.period_ends[-1])


def test_run_pbo_analysis_on_pure_noise_reports_a_defined_probability():
    # Both candidates trade pure noise -- no true edge either way. PBO should
    # come back as a well-formed probability; we don't assert a specific
    # value since it's a stochastic sample, only that the machinery works
    # end-to-end and produces a sane, bounded report.
    panel = _monthly_panel(60, seed=7)
    a = _spec("a", 3, panel.period_ends[0], panel.period_ends[-1])
    b = _spec("b", 9, panel.period_ends[0], panel.period_ends[-1])
    report = run_pbo_analysis(
        [a, b], panel, period_start=panel.period_ends[0], period_end=panel.period_ends[-1], num_blocks=6, embargo_months=1
    )
    assert 0.0 <= report.probability_of_backtest_overfitting <= 1.0
    assert report.num_splits > 0
    assert len(report.logits) == report.num_splits
    assert set(report.per_candidate_selection_count) == {"a", "b"}
    assert sum(report.per_candidate_selection_count.values()) == report.num_splits


def test_run_pbo_analysis_raises_when_purging_leaves_no_periods():
    panel = _monthly_panel(24, seed=3)
    a = _spec("a", 3, panel.period_ends[0], panel.period_ends[-1])
    b = _spec("b", 6, panel.period_ends[0], panel.period_ends[-1])
    with pytest.raises(ValueError):
        run_pbo_analysis(
            [a, b], panel, period_start=panel.period_ends[0], period_end=panel.period_ends[-1],
            num_blocks=2, purge_months=100, embargo_months=100,
        )
