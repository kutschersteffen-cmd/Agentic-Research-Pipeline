from arp.replication.sanity_check import SanityCheckAssessment, SanityCheckFinding, sanity_check_report
from arp.schemas.strategy_replication import (
    BacktestResult,
    LegPerformance,
    ReplicationComparisonReport,
    ReplicationVerdict,
    ReportedPerformance,
    SignalType,
    StrategySpec,
)


def _spec() -> StrategySpec:
    return StrategySpec(
        paper_citation="Test (2020)",
        paper_title="Test paper",
        strategy_name="test momentum",
        signal_type=SignalType.MOMENTUM,
        universe_description="synthetic",
        formation_period_months=6,
        holding_period_months=6,
        num_portfolios=10,
        long_leg_portfolio=1,
        short_leg_portfolio=10,
        sample_period_start="2000-01-01",
        sample_period_end="2010-01-01",
    )


def _report(**overrides) -> ReplicationComparisonReport:
    in_sample = BacktestResult(
        spec_id="spec_x",
        period_label="in_sample",
        period_start="2000-01-01",
        period_end="2010-01-01",
        data_source="test",
        universe_size=200,
        periods=[],
        long_short=LegPerformance(annualized_return_pct=12.0, sharpe_ratio=0.8, t_stat=3.0),
    )
    defaults = dict(
        spec_id="spec_x",
        in_sample=in_sample,
        out_of_sample=None,
        reported_performance=ReportedPerformance(long_short=LegPerformance(annualized_return_pct=12.0)),
        verdict=ReplicationVerdict.REPLICATED,
        verdict_notes="looks fine",
    )
    defaults.update(overrides)
    return ReplicationComparisonReport(**defaults)


async def test_sanity_check_report_returns_assessment_and_usage(fake_llm):
    assessment_in = SanityCheckAssessment(plausible=True, findings=[], summary="Looks reasonable.")
    llm = fake_llm({"SanityCheckAssessment": [assessment_in]})
    assessment, usage = await sanity_check_report(_spec(), _report(), llm)
    assert assessment.plausible is True
    assert usage.input_tokens == 10


async def test_sanity_check_prompt_includes_key_figures(fake_llm):
    assessment_in = SanityCheckAssessment(
        plausible=False,
        findings=[SanityCheckFinding(concern="implausible_sharpe", explanation="Sharpe of 0.8 is fine actually, this is a test")],
        summary="test",
    )
    llm = fake_llm({"SanityCheckAssessment": [assessment_in]})
    report = _report()
    await sanity_check_report(_spec(), report, llm)
    prompt = llm.prompts[0]
    assert "annualized_return=12.0" in prompt
    assert "Universe size: 200" in prompt
    assert "replicated" in prompt  # verdict.value
