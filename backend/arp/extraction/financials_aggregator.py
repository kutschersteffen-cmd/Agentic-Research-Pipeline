from __future__ import annotations

from arp.extraction.financials_extractor_agent import FinancialsExtractionDraft, SpendSectionDraft
from arp.extraction.financials_verifier_agent import FinancialsVerifierOutput
from arp.extraction.segment_aggregator import build_segments
from arp.extraction.segment_extractor_agent import SegmentExtractionDraft
from arp.extraction.segment_verifier_agent import SegmentVerifierOutput
from arp.extraction.spend_aggregator import build_spend_record
from arp.extraction.spend_extractor_agent import SpendExtractionDraft
from arp.extraction.spend_verifier_agent import SpendVerifierOutput
from arp.schemas.common import SourceDocument
from arp.schemas.financials import CompanyFinancialsRecord, SpendSummary
from arp.schemas.spend import SpendTopic


def _spend_summary(
    topic: SpendTopic,
    company_id: str,
    ticker: str | None,
    name: str,
    section_draft: SpendSectionDraft,
    draft_confidence: float,
    currency: str | None,
    fiscal_period: str | None,
    section_agree: bool,
    corrected_section: SpendSectionDraft | None,
    section_notes: str,
    verifier_confidence: float,
    documents_by_id: dict[str, SourceDocument],
    fuzzy_threshold: float,
    confidence_review_threshold: float,
) -> tuple[SpendSummary, bool]:
    """Wraps one section (capex or rnd) of the combined draft/verifier in
    the shapes build_spend_record() already knows how to aggregate, so the
    grounding/review-flagging logic isn't duplicated for the combined
    pipeline.
    """
    draft = SpendExtractionDraft(
        total=section_draft.total,
        description=section_draft.description,
        description_citations=section_draft.description_citations,
        currency=currency,
        fiscal_period=fiscal_period,
        categories=section_draft.categories,
        conflicting_sources=section_draft.conflicting_sources,
        confidence=draft_confidence,
    )
    verifier = SpendVerifierOutput(
        agrees=section_agree,
        corrected_total=corrected_section.total if corrected_section else None,
        corrected_description=corrected_section.description if corrected_section else None,
        corrected_description_citations=corrected_section.description_citations if corrected_section else None,
        corrected_categories=corrected_section.categories if corrected_section else None,
        confidence=verifier_confidence,
        notes=section_notes,
    )
    record, needs_review = build_spend_record(
        topic, company_id, ticker, name, draft, verifier, documents_by_id, fuzzy_threshold, confidence_review_threshold
    )
    summary = SpendSummary(
        total=record.total,
        description=record.description,
        description_citations=record.description_citations,
        categories=record.categories,
        confidence=record.confidence,
        grounded=record.grounded,
        verifier_notes=record.verifier_notes,
        conflicting_sources=record.conflicting_sources,
    )
    return summary, needs_review


def build_financials_record(
    company_id: str,
    ticker: str | None,
    name: str,
    draft: FinancialsExtractionDraft,
    verifier: FinancialsVerifierOutput,
    documents_by_id: dict[str, SourceDocument],
    fuzzy_threshold: float,
    confidence_review_threshold: float,
) -> tuple[CompanyFinancialsRecord, bool]:
    """Merges the single combined extractor draft and single combined
    verifier pass into a final CompanyFinancialsRecord, applying the hard
    programmatic grounding check to every citation across all three
    sections. Returns (record, needs_review).
    """
    segment_draft = SegmentExtractionDraft(segments=draft.segments, confidence=draft.confidence)
    segment_verifier = SegmentVerifierOutput(
        agrees=verifier.segments_agree,
        corrected_segments=verifier.corrected_segments,
        confidence=verifier.confidence,
        notes=verifier.segments_notes,
    )
    segments, segments_needs_review = build_segments(
        segment_draft, segment_verifier, documents_by_id, fuzzy_threshold, confidence_review_threshold
    )
    segments_verifier_notes = None
    if not verifier.segments_agree:
        segments_verifier_notes = f"Verifier disagreed with the extractor: {verifier.segments_notes}"
    elif verifier.segments_notes:
        segments_verifier_notes = verifier.segments_notes

    capex, capex_needs_review = _spend_summary(
        SpendTopic.CAPEX,
        company_id,
        ticker,
        name,
        draft.capex,
        draft.confidence,
        draft.currency,
        draft.fiscal_period,
        verifier.capex_agree,
        verifier.corrected_capex,
        verifier.capex_notes,
        verifier.confidence,
        documents_by_id,
        fuzzy_threshold,
        confidence_review_threshold,
    )
    rnd, rnd_needs_review = _spend_summary(
        SpendTopic.RND,
        company_id,
        ticker,
        name,
        draft.rnd,
        draft.confidence,
        draft.currency,
        draft.fiscal_period,
        verifier.rnd_agree,
        verifier.corrected_rnd,
        verifier.rnd_notes,
        verifier.confidence,
        documents_by_id,
        fuzzy_threshold,
        confidence_review_threshold,
    )

    needs_review = segments_needs_review or capex_needs_review or rnd_needs_review

    record = CompanyFinancialsRecord(
        company_id=company_id,
        ticker=ticker,
        name=name,
        run_id="",
        currency=draft.currency,
        fiscal_period=draft.fiscal_period,
        segments=segments,
        segments_verifier_notes=segments_verifier_notes,
        capex=capex,
        rnd=rnd,
        overall_confidence=verifier.confidence,
        needs_review=needs_review,
    )
    return record, needs_review
