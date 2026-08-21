from __future__ import annotations

from arp.extraction.financials_extractor_agent import SpendSectionDraft
from arp.extraction.spend_extractor_agent import AmountMetricDraft, SpendCategoryDraft
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
    section: SpendSectionDraft,
    draft_confidence: float,
    currency: str | None,
    fiscal_period: str | None,
    *,
    verifier_agrees: bool,
    corrected_section: SpendSectionDraft | None,
    verifier_confidence: float,
    verifier_notes: str,
    documents_by_id: dict[str, SourceDocument],
    fuzzy_threshold: float,
    confidence_review_threshold: float,
) -> tuple[SpendExtractionRecord, bool]:
    """Merges one section's (CapEx's or R&D's) extractor draft and the
    independent verifier's correction for it into a final
    SpendExtractionRecord, applying the hard programmatic grounding check
    to every citation across the total, description, and each category.
    Returns (record, needs_review). Takes the section/correction and the
    surrounding fields directly rather than a standalone spend-only draft/
    verifier model, since financials_aggregator.py -- the only caller --
    always has a combined-pipeline draft/verifier in hand, not a
    standalone one; `currency`/`fiscal_period` are top-level fields on the
    combined draft, shared by both sections, not part of SpendSectionDraft
    itself.
    """
    # Mirrors what corrected_section carries field-by-field -- kept as
    # separate optionals (not just `corrected_section.x`) since each of
    # total/description/categories may independently be corrected or left
    # as the section's original default, same as when this logic lived
    # behind a standalone SpendVerifierOutput model.
    corrected_total = corrected_section.total if corrected_section is not None else None
    corrected_description = corrected_section.description if corrected_section is not None else None
    corrected_description_citations = corrected_section.description_citations if corrected_section is not None else None
    corrected_categories = corrected_section.categories if corrected_section is not None else None

    total_draft = section.total if verifier_agrees or corrected_total is None else corrected_total
    if verifier_agrees or corrected_description is None:
        # Either the verifier agreed outright, or it disagreed about
        # something else (e.g. the total) and left the description
        # untouched -- either way section.description_citations still
        # support the description text being shown.
        description = section.description
        description_citations_draft = section.description_citations
    else:
        # A verifier-supplied description can carry its own citations (a
        # full corrected SpendSectionDraft); section.description_citations
        # supported different (rejected) text, so they're never reused
        # here regardless.
        description = corrected_description
        description_citations_draft = corrected_description_citations or []
    categories_draft = section.categories if verifier_agrees else (corrected_categories or section.categories)
    conflicting_sources = section.conflicting_sources or any(c.conflicting_sources for c in categories_draft)

    final_confidence = min(draft_confidence, verifier_confidence)

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
    if not verifier_agrees:
        notes_parts.append(f"Verifier disagreed with the extractor: {verifier_notes}")
    elif verifier_notes:
        notes_parts.append(verifier_notes)
    if not record_grounded:
        notes_parts.append("One or more citations failed the programmatic grounding check.")

    needs_review = (
        not verifier_agrees
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
        currency=currency,
        fiscal_period=fiscal_period,
        categories=categories,
        confidence=final_confidence,
        grounded=record_grounded,
        verifier_notes=" ".join(notes_parts).strip() or None,
        conflicting_sources=conflicting_sources,
        overall_confidence=final_confidence,
        needs_review=needs_review,
    )
    return record, needs_review
