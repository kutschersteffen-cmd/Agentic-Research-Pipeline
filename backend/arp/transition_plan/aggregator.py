from __future__ import annotations

from arp.grounding import ground_citations
from arp.schemas.common import SourceDocument
from arp.schemas.transition_plan import IndicatorAssessment, TransitionPlanIndicator, Verdict
from arp.transition_plan.indicator_agent import IndicatorAnswerDraft
from arp.transition_plan.verifier_agent import IndicatorVerifierOutput


def build_indicator_assessment(
    indicator: TransitionPlanIndicator,
    draft: IndicatorAnswerDraft,
    verifier: IndicatorVerifierOutput,
    documents_by_id: dict[str, SourceDocument],
    fuzzy_threshold: float,
) -> IndicatorAssessment:
    """Merges the drafted verdict and the independent verifier pass into a
    final IndicatorAssessment, applying the hard programmatic grounding check
    (arp/grounding.py) on top of both LLM opinions -- mirrors
    arp/extraction/aggregator.py's build_extracted_field. The paper's tool
    reports a single LLM's self-cited source page numbers as-is; here, a
    verdict is only trusted at full confidence once a second, independent
    analyst pass agrees with it AND at least one of its citations is
    independently verified against the real document text.
    """
    final_verdict = draft.verdict if verifier.agrees else (verifier.corrected_verdict or draft.verdict)

    if verifier.agrees:
        # draft.citations were written to support draft.verdict, which is
        # final_verdict here, so they're the right citations to check and show.
        grounded_citations = ground_citations(draft.citations, documents_by_id, fuzzy_threshold)
    else:
        # IndicatorVerifierOutput carries no citations of its own -- draft.citations
        # supported draft.verdict, a call the verifier just overruled, so they
        # can't be reused to back final_verdict.
        grounded_citations = []
    any_grounded = any(c.grounded for c in grounded_citations)

    if final_verdict == Verdict.NA:
        base_confidence = 1.0
    elif any_grounded:
        base_confidence = 1.0
    elif grounded_citations:
        # Citations were offered but none independently verified -- the
        # verdict may still be right, but nothing backs it mechanically.
        base_confidence = 0.3
    else:
        # A YES/NO verdict with no citations at all is the least trustworthy case.
        base_confidence = 0.2

    # An NA verdict both analysts agree on needs no discounting by the
    # verifier's own stated confidence -- there's nothing to be grounded.
    confidence = base_confidence if final_verdict == Verdict.NA else min(base_confidence, verifier.confidence)

    notes_parts: list[str] = []
    if not verifier.agrees:
        notes_parts.append(f"Verifier disagreed with the drafted verdict: {verifier.notes}")
    elif verifier.notes:
        notes_parts.append(verifier.notes)
    if final_verdict != Verdict.NA and not any_grounded:
        notes_parts.append(
            "One or more citations failed the programmatic grounding check."
            if grounded_citations
            else "No grounded citation supports this verdict."
        )

    needs_review = (final_verdict != Verdict.NA and not any_grounded) or not verifier.agrees

    return IndicatorAssessment(
        number=indicator.number,
        identifier=indicator.identifier,
        category=indicator.category,
        walk_or_talk=indicator.walk_or_talk,
        question=indicator.question,
        verdict=final_verdict,
        answer=draft.answer,
        citations=grounded_citations,
        grounded=any_grounded,
        confidence=confidence,
        needs_review=needs_review,
        verifier_notes=" ".join(notes_parts).strip() or None,
    )


def no_evidence_indicator(indicator: TransitionPlanIndicator) -> IndicatorAssessment:
    """No matching evidence at all is the common case at scale (most
    companies won't discuss most indicators) -- reported plainly as NA
    rather than routed to review, matching the analogous no_evidence_field
    convention in arp/extraction/aggregator.py.
    """
    return IndicatorAssessment(
        number=indicator.number,
        identifier=indicator.identifier,
        category=indicator.category,
        walk_or_talk=indicator.walk_or_talk,
        question=indicator.question,
        verdict=Verdict.NA,
        answer="No evidence relevant to this indicator was found in the available documents.",
        confidence=0.0,
        needs_review=False,
    )


def answer_failed_indicator(indicator: TransitionPlanIndicator, error: str) -> IndicatorAssessment:
    """The model never produced a schema-valid answer for this indicator
    after every self-correction retry (arp/transition_plan/indicator_graph.py
    catches the resulting ValidationError here) -- reported as its own
    distinct, clearly-flagged state rather than silently defaulting to a
    real NA, so it can't be confused with the paper's own "not applicable"
    and isn't quietly absorbed into the disclosure-rate denominator as if
    it were a real determination.
    """
    return IndicatorAssessment(
        number=indicator.number,
        identifier=indicator.identifier,
        category=indicator.category,
        walk_or_talk=indicator.walk_or_talk,
        question=indicator.question,
        verdict=Verdict.NA,
        answer=f"Assessment failed: the model could not produce a schema-valid answer for this indicator. {error}",
        confidence=0.0,
        needs_review=True,
        assessment_error=True,
    )
