from arp.replication.spec_revision import _current_revision_draft, revise_spec_via_instruction
from arp.schemas.strategy_replication import RebalanceFrequency, SignalType, StrategySpec


def _spec(**overrides) -> StrategySpec:
    defaults = dict(
        paper_citation="Test (2020)",
        paper_title="Test paper",
        strategy_name="test momentum",
        signal_type=SignalType.MOMENTUM,
        universe_description="NYSE",
        formation_period_months=6,
        holding_period_months=6,
        num_portfolios=10,
        long_leg_portfolio=1,
        short_leg_portfolio=10,
        rebalance_frequency=RebalanceFrequency.MONTHLY,
        sample_period_start="1965-01-01",
        sample_period_end="1989-12-31",
        grounded=True,
        confidence=0.9,
    )
    defaults.update(overrides)
    return StrategySpec(**defaults)


async def test_revise_changes_only_the_targeted_field_and_clears_grounding(fake_llm):
    spec = _spec()
    revised_draft = _current_revision_draft(spec).model_copy(update={"rebalance_frequency": RebalanceFrequency.QUARTERLY})
    llm = fake_llm({"StrategySpecRevisionDraft": [revised_draft]})

    updated, usage = await revise_spec_via_instruction(spec, "switch to quarterly rebalancing", llm)

    assert updated.rebalance_frequency == RebalanceFrequency.QUARTERLY
    assert updated.holding_period_months == 6  # untouched
    assert updated.grounded is False
    assert updated.needs_review is True
    assert "switch to quarterly rebalancing" in updated.extraction_notes
    assert updated.paper_citation == spec.paper_citation  # identity field, never revisable
    assert usage.input_tokens >= 0


async def test_revise_with_no_actual_change_leaves_grounding_untouched(fake_llm):
    spec = _spec()
    unchanged_draft = _current_revision_draft(spec)  # LLM "revises" but changes nothing
    llm = fake_llm({"StrategySpecRevisionDraft": [unchanged_draft]})

    updated, _usage = await revise_spec_via_instruction(spec, "no-op instruction", llm)

    assert updated.grounded is True
    assert updated.needs_review is False
    assert updated.extraction_notes == ""


async def test_revise_preserves_existing_citations_list(fake_llm):
    from arp.schemas.common import Citation, DocType

    spec = _spec(citations=[Citation(doc_id="paper_doc", doc_type=DocType.RESEARCH_PAPER, quote="a real quote")])
    revised_draft = _current_revision_draft(spec).model_copy(update={"holding_period_months": 12})
    llm = fake_llm({"StrategySpecRevisionDraft": [revised_draft]})

    updated, _usage = await revise_spec_via_instruction(spec, "hold for 12 months instead", llm)

    assert updated.holding_period_months == 12
    assert len(updated.citations) == 1  # not deleted, even though grounded is now False
    assert updated.grounded is False
