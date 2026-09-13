from arp.replication.spec_extractor_agent import StrategySpecDraft
from arp.replication.spec_graph import extract_strategy_spec
from arp.replication.spec_verifier_agent import SpecVerifierOutput
from arp.schemas.common import Citation, DocType
from arp.schemas.strategy_replication import RebalanceFrequency, ReportedPerformance, SignalType, WeightingScheme

_PAPER_TEXT = (
    "We form decile portfolios based on the prior 6-month formation period return and hold them "
    "for 6 months. NYSE ordinary common shares, sample period 1965 to 1989. The zero-cost "
    "winners-minus-losers portfolio earns approximately 1% per month, t-statistic 3.07."
)

_QUOTE = "the prior 6-month formation period return and hold them for 6 months"


def _draft(confidence=0.9) -> StrategySpecDraft:
    return StrategySpecDraft(
        paper_title="Test momentum paper",
        strategy_name="6-6 momentum",
        signal_type=SignalType.MOMENTUM,
        universe_description="NYSE ordinary common shares",
        formation_period_months=6,
        holding_period_months=6,
        rebalance_frequency=RebalanceFrequency.MONTHLY,
        num_portfolios=10,
        long_leg_portfolio=1,
        short_leg_portfolio=10,
        weighting=WeightingScheme.EQUAL,
        sample_period_start="1965-01-01",
        sample_period_end="1989-12-31",
        reported_performance=ReportedPerformance(),
        citations=[Citation(doc_id="paper_doc", doc_type=DocType.RESEARCH_PAPER, quote=_QUOTE)],
        confidence=confidence,
    )


async def test_extractor_and_verifier_agree_produces_grounded_spec(fake_llm):
    draft = _draft()
    llm = fake_llm(
        {
            "StrategySpecDraft": [draft],
            "SpecVerifierOutput": [SpecVerifierOutput(agrees=True, confidence=0.85, notes="Looks right.")],
        }
    )
    spec, needs_review, usages = await extract_strategy_spec("Test (2020)", _PAPER_TEXT, llm=llm)

    assert spec.grounded is True
    assert spec.formation_period_months == 6
    assert spec.holding_period_months == 6
    assert spec.confidence == 0.85  # min(draft.confidence=0.9, verifier.confidence=0.85)
    assert needs_review is False
    assert len(usages) == 2


async def test_verifier_correction_overrides_the_draft(fake_llm):
    draft = _draft()
    corrected = _draft()
    corrected.holding_period_months = 12  # verifier disagrees with the draft's holding period
    corrected.citations = [Citation(doc_id="paper_doc", doc_type=DocType.RESEARCH_PAPER, quote=_QUOTE)]
    llm = fake_llm(
        {
            "StrategySpecDraft": [draft],
            "SpecVerifierOutput": [
                SpecVerifierOutput(agrees=False, corrected=corrected, confidence=0.8, notes="Holding period was wrong.")
            ],
        }
    )
    spec, needs_review, _ = await extract_strategy_spec("Test (2020)", _PAPER_TEXT, llm=llm)

    assert spec.holding_period_months == 12
    assert needs_review is True  # verifier disagreement always routes to review, even with a correction
    assert "Verifier disagreed" in (spec.verifier_notes or "")


async def test_ungrounded_citation_is_flagged_for_review(fake_llm):
    draft = _draft()
    draft.citations = [Citation(doc_id="paper_doc", doc_type=DocType.RESEARCH_PAPER, quote="this text is not in the paper at all")]
    llm = fake_llm(
        {
            "StrategySpecDraft": [draft],
            "SpecVerifierOutput": [SpecVerifierOutput(agrees=True, confidence=0.9, notes="")],
        }
    )
    spec, needs_review, _ = await extract_strategy_spec("Test (2020)", _PAPER_TEXT, llm=llm)

    assert spec.grounded is False
    assert needs_review is True
