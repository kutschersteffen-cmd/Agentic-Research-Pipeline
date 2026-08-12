from __future__ import annotations

from arp.extraction.extractor_agent import ExtractionDraft
from arp.extraction.verifier_agent import VerifierOutput
from arp.grounding import ground_citations
from arp.schemas.common import SourceDocument
from arp.schemas.datapoints import ExtractedField, FieldDefinition


def build_extracted_field(
    field: FieldDefinition,
    draft: ExtractionDraft,
    verifier: VerifierOutput,
    documents_by_id: dict[str, SourceDocument],
    fuzzy_threshold: float,
    confidence_review_threshold: float,
) -> tuple[ExtractedField, bool]:
    """Merges the extractor draft and the independent verifier pass into a
    final ExtractedField, applying the hard programmatic grounding check on
    top of both LLM opinions. Returns (field, needs_review).
    """
    grounded_citations = ground_citations(draft.citations, documents_by_id, fuzzy_threshold)
    all_grounded = all(c.grounded for c in grounded_citations) if grounded_citations else (draft.value is None)

    final_value = draft.value if verifier.agrees else verifier.corrected_value
    final_confidence = min(draft.confidence, verifier.confidence) if draft.value is not None else 0.0

    notes_parts: list[str] = []
    if not verifier.agrees:
        notes_parts.append(f"Verifier disagreed with the extractor: {verifier.notes}")
    elif verifier.notes:
        notes_parts.append(verifier.notes)
    if draft.value is not None and not all_grounded:
        notes_parts.append("One or more citations failed the programmatic grounding check.")

    needs_review = (
        (draft.value is not None and not all_grounded)
        or not verifier.agrees
        or draft.conflicting_sources
        or (draft.value is not None and final_confidence < confidence_review_threshold)
    )

    field_result = ExtractedField(
        field_id=field.field_id,
        field_name=field.name,
        value=final_value,
        raw_value_text=draft.raw_value_text,
        citations=grounded_citations,
        confidence=final_confidence,
        grounded=all_grounded,
        verifier_notes=" ".join(notes_parts).strip() or None,
        conflicting_sources=draft.conflicting_sources,
    )
    return field_result, needs_review


def no_evidence_field(field: FieldDefinition) -> tuple[ExtractedField, bool]:
    """A field with zero matching evidence is the common case at 4000-company
    scale (most companies won't discuss most data points) -- it is reported
    plainly rather than routed to human review, which would otherwise flood
    the review queue with "not disclosed" noise.
    """
    return (
        ExtractedField(
            field_id=field.field_id,
            field_name=field.name,
            value=None,
            confidence=0.0,
            grounded=False,
            verifier_notes="No evidence matching this field's keywords was found in the available documents.",
        ),
        False,
    )
