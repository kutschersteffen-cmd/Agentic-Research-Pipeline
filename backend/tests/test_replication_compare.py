from arp.replication.compare import build_comparison_report
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
