from arp.replication.compare import build_comparison_report, significance_threshold
from arp.schemas.strategy_replication import (
    BacktestResult,
    LegPerformance,
    PortfolioPeriodReturn,
    ReplicationVerdict,
    ReportedPerformance,
)


def _periods(n=12):
    return [
        PortfolioPeriodReturn(
            period_end=f"2000-{(i % 12) + 1:02d}-01",
            long_return_pct=0.0,
            short_return_pct=0.0,
            long_short_return_pct=0.0,
            num_long=1,
            num_short=1,
        )
        for i in range(n)
    ]


def _result(annualized_return_pct, t_stat, n_periods=12, label="in_sample") -> BacktestResult:
    return BacktestResult(
        spec_id="spec_test",
        period_label=label,
        period_start="2000-01-01",
        period_end="2000-12-01",
        data_source="test",
        universe_size=10,
        periods=_periods(n_periods),
        long_short=LegPerformance(annualized_return_pct=annualized_return_pct, t_stat=t_stat),
    )


def _reported(annualized_return_pct=12.0) -> ReportedPerformance:
    return ReportedPerformance(long_short=LegPerformance(annualized_return_pct=annualized_return_pct))


def test_replicated_when_magnitude_close_to_reported():
    report = build_comparison_report(_result(12.0, t_stat=3.0), _reported(12.0))
    assert report.verdict == ReplicationVerdict.REPLICATED
    assert report.in_sample_return_gap_pp == 0.0


def test_partially_replicated_on_large_magnitude_gap():
    report = build_comparison_report(_result(4.0, t_stat=3.0), _reported(12.0))
    assert report.verdict == ReplicationVerdict.PARTIALLY_REPLICATED


def test_not_replicated_on_wrong_sign():
    report = build_comparison_report(_result(-5.0, t_stat=-3.0), _reported(12.0))
    assert report.verdict == ReplicationVerdict.NOT_REPLICATED


def test_not_replicated_on_insignificant_t_stat():
    report = build_comparison_report(_result(12.0, t_stat=1.0), _reported(12.0))
    assert report.verdict == ReplicationVerdict.NOT_REPLICATED


def test_insufficient_data_below_period_floor():
    report = build_comparison_report(_result(12.0, t_stat=3.0, n_periods=6), _reported(12.0))
    assert report.verdict == ReplicationVerdict.INSUFFICIENT_DATA


def test_replicated_without_reported_figure_notes_the_gap_in_lieu():
    report = build_comparison_report(_result(12.0, t_stat=3.0), ReportedPerformance())
    assert report.verdict == ReplicationVerdict.REPLICATED
    assert report.in_sample_return_gap_pp is None
    assert "not available" in report.verdict_notes


def test_decayed_out_of_sample_when_effect_vanishes():
    in_sample = _result(12.0, t_stat=3.0)
    out_of_sample = _result(0.5, t_stat=0.2, label="out_of_sample")
    report = build_comparison_report(in_sample, _reported(12.0), out_of_sample=out_of_sample)
    assert report.verdict == ReplicationVerdict.DECAYED_OUT_OF_SAMPLE


def test_out_of_sample_persistence_keeps_replicated_verdict():
    in_sample = _result(12.0, t_stat=3.0)
    out_of_sample = _result(11.0, t_stat=2.8, label="out_of_sample")
    report = build_comparison_report(in_sample, _reported(12.0), out_of_sample=out_of_sample)
    assert report.verdict == ReplicationVerdict.REPLICATED
    assert report.out_of_sample_return_gap_pp == -1.0


def test_not_replicated_in_sample_is_not_overridden_by_out_of_sample():
    in_sample = _result(-5.0, t_stat=-3.0)
    out_of_sample = _result(20.0, t_stat=5.0, label="out_of_sample")
    report = build_comparison_report(in_sample, _reported(12.0), out_of_sample=out_of_sample)
    assert report.verdict == ReplicationVerdict.NOT_REPLICATED


def test_significance_threshold_stays_flat_for_a_single_trial():
    assert significance_threshold(1) == 2.0
    assert significance_threshold(0) == 2.0  # defensive floor, though StrategySpec itself enforces >=1


def test_significance_threshold_rises_toward_hlz_ceiling_with_more_trials():
    assert significance_threshold(10) == 2.5
    assert significance_threshold(100) == 3.0
    assert significance_threshold(10_000) == 3.0  # capped, never exceeds the HLZ-inspired ceiling


def test_more_trials_can_flip_a_marginally_significant_result_to_not_replicated():
    # t_stat=2.4 clears the flat 2.0 hurdle (num_trials_attempted=1) ...
    report_one_trial = build_comparison_report(_result(12.0, t_stat=2.4), _reported(12.0), num_trials_attempted=1)
    assert report_one_trial.verdict == ReplicationVerdict.REPLICATED
    # ... but not the 3.0 hurdle once 100+ variants were tried before landing on this spec.
    report_many_trials = build_comparison_report(_result(12.0, t_stat=2.4), _reported(12.0), num_trials_attempted=100)
    assert report_many_trials.verdict == ReplicationVerdict.NOT_REPLICATED
    assert "hurdle raised" in report_many_trials.verdict_notes


def test_deflated_sharpe_populated_on_a_real_return_series():
    periods = [
        PortfolioPeriodReturn(
            period_end=f"2000-{(i % 12) + 1:02d}-01",
            long_return_pct=0.0,
            short_return_pct=0.0,
            long_short_return_pct=1.0 if i % 2 == 0 else 0.5,
            num_long=1,
            num_short=1,
        )
        for i in range(24)
    ]
    in_sample = BacktestResult(
        spec_id="spec_test", period_label="in_sample", period_start="2000-01-01", period_end="2001-12-01",
        data_source="test", universe_size=10, periods=periods, long_short=LegPerformance(annualized_return_pct=9.0, t_stat=3.0),
    )
    report = build_comparison_report(in_sample, _reported(9.0), num_trials_attempted=5)
    assert report.deflated_sharpe is not None
    assert report.deflated_sharpe.n_obs == 24
    assert report.deflated_sharpe.n_trials == 5
    assert report.deflated_sharpe.deflated_sharpe_ratio is not None


def test_deflated_sharpe_none_with_fewer_than_two_periods():
    report = build_comparison_report(_result(12.0, t_stat=3.0, n_periods=1), _reported(12.0))
    assert report.deflated_sharpe is None
