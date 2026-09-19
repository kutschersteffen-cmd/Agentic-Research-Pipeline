from arp.replication.golden_set import (
    BacktestGoldenCase,
    GoldenCharacteristicData,
    GoldenPanelData,
    load_bundled_cases,
    run_golden_case,
    run_golden_set,
)
from arp.schemas.strategy_replication import RebalanceFrequency, SignalType, StrategySpec, WeightingScheme


def test_bundled_golden_set_all_pass():
    report = run_golden_set(load_bundled_cases())
    assert report.all_passed, [r.detail for r in report.results if not r.passed]
    assert report.total == 2


def _momentum_spec() -> StrategySpec:
    return StrategySpec(
        paper_citation="Test (2020)",
        paper_title="Test paper",
        strategy_name="test momentum",
        signal_type=SignalType.MOMENTUM,
        universe_description="synthetic",
        formation_period_months=3,
        holding_period_months=3,
        rebalance_frequency=RebalanceFrequency.MONTHLY,
        num_portfolios=2,
        long_leg_portfolio=1,
        short_leg_portfolio=2,
        weighting=WeightingScheme.EQUAL,
        sample_period_start="2000-01-01",
        sample_period_end="2001-12-01",
    )


def _panel_data() -> GoldenPanelData:
    period_ends = [f"2000-{m:02d}-01" for m in range(1, 13)] + [f"2001-{m:02d}-01" for m in range(1, 13)]
    return GoldenPanelData(
        period_ends=period_ends,
        returns={
            "WIN1": [None] + [0.02] * 23,
            "WIN2": [None] + [0.025] * 23,
            "LOSE1": [None] + [-0.01] * 23,
            "LOSE2": [None] + [-0.015] * 23,
        },
    )


def test_run_golden_case_passes_with_correct_expected_values():
    case = BacktestGoldenCase(
        case_id="c1",
        description="test",
        spec=_momentum_spec(),
        panel=_panel_data(),
        period_start="2000-01-01",
        period_end="2001-12-01",
        expected_long_short_annualized_return_pct=51.10686573463601,
        expected_num_periods=20,
    )
    result = run_golden_case(case)
    assert result.passed
    assert result.actual_num_periods == 20


def test_run_golden_case_fails_on_wrong_expected_return():
    case = BacktestGoldenCase(
        case_id="c2",
        description="test",
        spec=_momentum_spec(),
        panel=_panel_data(),
        period_start="2000-01-01",
        period_end="2001-12-01",
        expected_long_short_annualized_return_pct=999.0,  # deliberately wrong
        tolerance_pct=0.001,
    )
    result = run_golden_case(case)
    assert not result.passed
    assert "annualized_return_pct" in result.detail


def test_run_golden_case_fails_on_wrong_expected_period_count():
    case = BacktestGoldenCase(
        case_id="c3",
        description="test",
        spec=_momentum_spec(),
        panel=_panel_data(),
        period_start="2000-01-01",
        period_end="2001-12-01",
        expected_num_periods=999,
    )
    result = run_golden_case(case)
    assert not result.passed
    assert "num_periods" in result.detail


def test_run_golden_set_reports_failures_by_case_id():
    passing = BacktestGoldenCase(
        case_id="pass_case", description="", spec=_momentum_spec(), panel=_panel_data(),
        period_start="2000-01-01", period_end="2001-12-01", expected_num_periods=20,
    )
    failing = BacktestGoldenCase(
        case_id="fail_case", description="", spec=_momentum_spec(), panel=_panel_data(),
        period_start="2000-01-01", period_end="2001-12-01", expected_num_periods=1,
    )
    report = run_golden_set([passing, failing])
    assert report.total == 2
    assert report.passed == 1
    assert report.failed_case_ids == ["fail_case"]
    assert not report.all_passed


def test_golden_characteristic_data_roundtrips_to_characteristic_panel():
    data = GoldenCharacteristicData(period_ends=["2000-01-01"], values={"A": [1.5]})
    panel = data.to_characteristic_panel()
    assert panel.period_ends == ["2000-01-01"]
    assert panel.values == {"A": [1.5]}
