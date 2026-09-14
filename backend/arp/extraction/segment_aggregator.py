from __future__ import annotations

from arp.extraction.segment_extractor_agent import SegmentDraft, SegmentMetricDraft
from arp.grounding import ground_citations
from arp.schemas.common import SourceDocument
from arp.schemas.segments import BusinessSegment, SegmentMetric


def _build_metric(
    draft_metric: SegmentMetricDraft, documents_by_id: dict[str, SourceDocument], fuzzy_threshold: float
) -> SegmentMetric:
    citations = ground_citations(draft_metric.citations, documents_by_id, fuzzy_threshold)
    grounded = all(c.grounded for c in citations) if citations else (draft_metric.value is None)
    return SegmentMetric(
        value=draft_metric.value, raw_value_text=draft_metric.raw_value_text, citations=citations, grounded=grounded
    )


def build_segments(
    segments: list[SegmentDraft],
    draft_confidence: float,
    *,
    verifier_agrees: bool,
    corrected_segments: list[SegmentDraft] | None,
    verifier_confidence: float,
    verifier_notes: str,
    documents_by_id: dict[str, SourceDocument],
    fuzzy_threshold: float,
    confidence_review_threshold: float,
) -> tuple[list[BusinessSegment], bool]:
    """Merges the extractor's segment list and the independent verifier
    pass into a final segment list, applying the hard programmatic
    grounding check to every citation across every segment's description/
    revenue/income/assets. Returns (segments, needs_review). Takes the
    extractor/verifier's fields directly rather than their full draft/
    verifier models, since financials_aggregator.py -- the only caller --
    always has a combined-pipeline draft/verifier in hand, not a
    standalone segment-only one.
    """
    source_segments = segments if verifier_agrees else (corrected_segments or segments)
    final_confidence = min(draft_confidence, verifier_confidence)

    any_needs_review = not verifier_agrees or final_confidence < confidence_review_threshold

    built_segments: list[BusinessSegment] = []
    for seg_draft in source_segments:
        description_citations = ground_citations(seg_draft.description_citations, documents_by_id, fuzzy_threshold)
        description_grounded = all(c.grounded for c in description_citations) if description_citations else True
        revenue = _build_metric(seg_draft.revenue, documents_by_id, fuzzy_threshold)
        income = _build_metric(seg_draft.income, documents_by_id, fuzzy_threshold)
        assets = _build_metric(seg_draft.assets, documents_by_id, fuzzy_threshold)
        segment_grounded = description_grounded and revenue.grounded and income.grounded and assets.grounded

        if not segment_grounded or seg_draft.conflicting_sources:
            any_needs_review = True

        notes_parts: list[str] = []
        if not verifier_agrees:
            notes_parts.append(f"Verifier disagreed with the extractor: {verifier_notes}")
        elif verifier_notes:
            notes_parts.append(verifier_notes)
        if not segment_grounded:
            notes_parts.append("One or more citations failed the programmatic grounding check.")

        built_segments.append(
            BusinessSegment(
                name=seg_draft.name,
                description=seg_draft.description,
                description_citations=description_citations,
                revenue=revenue,
                income=income,
                assets=assets,
                currency=seg_draft.currency,
                fiscal_period=seg_draft.fiscal_period,
                confidence=final_confidence,
                grounded=segment_grounded,
                verifier_notes=" ".join(notes_parts).strip() or None,
                conflicting_sources=seg_draft.conflicting_sources,
            )
        )
    return built_segments, any_needs_review
