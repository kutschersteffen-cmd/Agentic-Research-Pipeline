from __future__ import annotations

from arp.grounding import ground_citations
from arp.schemas.common import SourceDocument
from arp.schemas.transition_plan import IndicatorAssessment, TransitionPlanIndicator, Verdict
from arp.transition_plan.indicator_agent import IndicatorAnswerDraft


def build_indicator_assessment(
    indicator: TransitionPlanIndicator,
    draft: IndicatorAnswerDraft,
    documents_by_id: dict[str, SourceDocument],
    fuzzy_threshold: float,
) -> IndicatorAssessment:
    """Applies the hard programmatic grounding check (arp/grounding.py) on
    top of the model's YES/NO/NA verdict -- the paper's tool reports the
    LLM's self-cited source page numbers as-is; here, a verdict is only
    trusted at full confidence once at least one of its citations is
    independently verified against the real document text.
    """
    grounded_citations = ground_citations(draft.citations, documents_by_id, fuzzy_threshold)
    any_grounded = any(c.grounded for c in grounded_citations)

    if draft.verdict == Verdict.NA:
        confidence = 1.0
        needs_review = False
    elif any_grounded:
        confidence = 1.0
        needs_review = False
    elif grounded_citations:
        # Citations were offered but none independently verified -- the
        # verdict may still be right, but nothing backs it mechanically.
        confidence = 0.3
        needs_review = True
    else:
        # A YES/NO verdict with no citations at all is the least trustworthy case.
        confidence = 0.2
        needs_review = True

    return IndicatorAssessment(
        number=indicator.number,
        identifier=indicator.identifier,
        category=indicator.category,
        walk_or_talk=indicator.walk_or_talk,
        question=indicator.question,
        verdict=draft.verdict,
        answer=draft.answer,
        citations=grounded_citations,
        grounded=any_grounded,
        confidence=confidence,
        needs_review=needs_review,
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
