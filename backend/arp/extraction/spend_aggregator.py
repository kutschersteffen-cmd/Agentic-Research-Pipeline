from __future__ import annotations

from arp.extraction.spend_extractor_agent import AmountMetricDraft, SpendCategoryDraft, SpendExtractionDraft
from arp.extraction.spend_verifier_agent import SpendVerifierOutput
from arp.grounding import ground_citations
from arp.schemas.common import SourceDocument
from arp.schemas.spend import AmountMetric, SpendCategory, SpendExtractionRecord, SpendTopic


def _build_metric(
    draft_metric: AmountMetricDraft, documents_by_id: dict[str, SourceDocument], fuzzy_threshold: float
) -> AmountMetric:
    citations = ground_citations(draft_metric.citations, documents_by_id, fuzzy_threshold)
    grounded = all(c.grounded for c in citations) if citations else (draft_metric.value is None)
    return AmountMetric(
        value=draft_metric.value, raw_value_text=draft_metric.raw_value_text, citations=citations, grounded=grounded
    )


def _build_category(
    draft_category: SpendCategoryDraft,
    documents_by_id: dict[str, SourceDocument],
    fuzzy_threshold: float,
    category_confidence: float,
) -> SpendCategory:
    description_citations = ground_citations(draft_category.description_citations, documents_by_id, fuzzy_threshold)
    # A real description with zero citations is not grounded -- only the
    # absence of a description at all is trivially "nothing to ground".
    description_grounded = (
        all(c.grounded for c in description_citations) if description_citations else (draft_category.description is None)
    )
    amount = _build_metric(draft_category.amount, documents_by_id, fuzzy_threshold)
    return SpendCategory(
        name=draft_category.name,
        description=draft_category.description,
        description_citations=description_citations,
        amount=amount,
        confidence=category_confidence,
        grounded=description_grounded and amount.grounded,
        conflicting_sources=draft_category.conflicting_sources,
    )


def build_spend_record(
    topic: SpendTopic,
    company_id: str,
    ticker: str | None,
    name: str,
    draft: SpendExtractionDraft,
    verifier: SpendVerifierOutput,
    documents_by_id: dict[str, SourceDocument],
    fuzzy_threshold: float,
    confidence_review_threshold: float,
) -> tuple[SpendExtractionRecord, bool]:
    """Merges the extractor draft and the independent verifier pass into a
    final SpendExtractionRecord, applying the hard programmatic grounding
    check to every citation across the total, description, and each
    category. Returns (record, needs_review).
    """
    total_draft = draft.total if verifier.agrees or verifier.corrected_total is None else verifier.corrected_total
    if verifier.agrees or verifier.corrected_description is None:
        # Either the verifier agreed outright, or it disagreed about
        # something else (e.g. the total) and left the description
        # untouched -- either way draft.description_citations still
        # support the description text being shown.
        description = draft.description
        description_citations_draft = draft.description_citations
    else:
        # A verifier-supplied description can carry its own citations (the
        # combined financials pipeline re-wraps a full SpendSectionDraft
        # that has them); draft.description_citations supported different
        # (rejected) text, so they're never reused here regardless.
        description = verifier.corrected_description
        description_citations_draft = verifier.corrected_description_citations or []
    categories_draft = draft.categories if verifier.agrees else (verifier.corrected_categories or draft.categories)
    conflicting_sources = draft.conflicting_sources or any(c.conflicting_sources for c in categories_draft)

    final_confidence = min(draft.confidence, verifier.confidence)

    total = _build_metric(total_draft, documents_by_id, fuzzy_threshold)
    description_citations = ground_citations(description_citations_draft, documents_by_id, fuzzy_threshold)
    # A real description with zero citations is not grounded -- only the
    # absence of a description at all is trivially "nothing to ground".
    description_grounded = all(c.grounded for c in description_citations) if description_citations else (description is None)
    categories = [
        _build_category(c, documents_by_id, fuzzy_threshold, final_confidence) for c in categories_draft
    ]

    record_grounded = total.grounded and description_grounded and all(c.grounded for c in categories)

    notes_parts: list[str] = []
    if not verifier.agrees:
        notes_parts.append(f"Verifier disagreed with the extractor: {verifier.notes}")
    elif verifier.notes:
        notes_parts.append(verifier.notes)
    if not record_grounded:
        notes_parts.append("One or more citations failed the programmatic grounding check.")

    needs_review = (
        not verifier.agrees
        or not record_grounded
        or conflicting_sources
        or (total.value is not None and final_confidence < confidence_review_threshold)
    )

    record = SpendExtractionRecord(
        company_id=company_id,
        ticker=ticker,
        name=name,
        topic=topic,
        run_id="",
        total=total,
        description=description,
        description_citations=description_citations,
        currency=draft.currency,
        fiscal_period=draft.fiscal_period,
        categories=categories,
        confidence=final_confidence,
        grounded=record_grounded,
        verifier_notes=" ".join(notes_parts).strip() or None,
        conflicting_sources=conflicting_sources,
        overall_confidence=final_confidence,
        needs_review=needs_review,
    )
    return record, needs_review
