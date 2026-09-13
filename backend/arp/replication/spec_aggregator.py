from __future__ import annotations

from arp.grounding import ground_citations
from arp.replication.spec_extractor_agent import StrategySpecDraft
from arp.replication.spec_verifier_agent import SpecVerifierOutput
from arp.schemas.common import SourceDocument
from arp.schemas.strategy_replication import StrategySpec


def build_strategy_spec(
    paper_citation: str,
    draft: StrategySpecDraft,
    verifier: SpecVerifierOutput,
    documents_by_id: dict[str, SourceDocument],
    fuzzy_threshold: float,
    confidence_review_threshold: float,
) -> tuple[StrategySpec, bool]:
    """Merges the extractor draft and the independent verifier pass into a
    final StrategySpec, applying the same programmatic citation-grounding
    check used everywhere else in this codebase. Returns (spec, needs_review).
    """
    if verifier.agrees:
        final = draft
    elif verifier.corrected is not None:
        final = verifier.corrected
    else:
        # Verifier flagged a problem but didn't supply a full correction --
        # keep the draft (it's the only complete spec available) but this
        # is never left un-reviewed.
        final = draft

    citations = ground_citations(final.citations, documents_by_id, fuzzy_threshold)
    all_grounded = all(c.grounded for c in citations) if citations else False
    final_confidence = min(draft.confidence, verifier.confidence)

    notes_parts: list[str] = []
    if not verifier.agrees:
        notes_parts.append(f"Verifier disagreed with the extractor: {verifier.notes}")
        if verifier.corrected is None:
            notes_parts.append("Verifier did not supply a corrected specification.")
    elif verifier.notes:
        notes_parts.append(verifier.notes)
    if not all_grounded:
        notes_parts.append("One or more citations failed the programmatic grounding check, or none were provided.")

    needs_review = (
        not all_grounded
        or not verifier.agrees
        or final_confidence < confidence_review_threshold
    )

    spec = StrategySpec(
        paper_citation=paper_citation,
        paper_title=final.paper_title,
        strategy_name=final.strategy_name,
        signal_type=final.signal_type,
        universe_description=final.universe_description,
        formation_period_months=final.formation_period_months,
        skip_month=final.skip_month,
        holding_period_months=final.holding_period_months,
        rebalance_frequency=final.rebalance_frequency,
        num_portfolios=final.num_portfolios,
        long_leg_portfolio=final.long_leg_portfolio,
        short_leg_portfolio=final.short_leg_portfolio,
        weighting=final.weighting,
        characteristic_name=final.characteristic_name,
        characteristic_lag_months=final.characteristic_lag_months,
        sample_period_start=final.sample_period_start,
        sample_period_end=final.sample_period_end,
        reported_performance=final.reported_performance,
        citations=citations,
        grounded=all_grounded,
        confidence=final_confidence,
        needs_review=needs_review,
        verifier_notes=" ".join(notes_parts).strip() or None,
    )
    return spec, needs_review


def no_evidence_spec(paper_citation: str) -> tuple[StrategySpec, bool]:
    """No chunk of the supplied paper text matched the methodology/results
    keywords select_relevant_chunks looks for -- most likely the wrong
    document, or one with no machine-readable text (a scanned PDF)."""
    return (
        StrategySpec(
            paper_citation=paper_citation,
            paper_title="",
            strategy_name="",
            signal_type="momentum",  # type: ignore[arg-type]
            universe_description="",
            formation_period_months=0,
            holding_period_months=0,
            short_leg_portfolio=0,
            sample_period_start="",
            sample_period_end="",
            confidence=0.0,
            needs_review=True,
            verifier_notes="No evidence matching strategy-methodology keywords was found in the supplied paper text.",
        ),
        True,
    )
