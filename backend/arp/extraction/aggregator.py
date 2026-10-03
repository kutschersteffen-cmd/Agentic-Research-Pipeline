from __future__ import annotations

from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue
from arp.extraction.verifier_agent import VerifierOutput
from arp.grounding import ground_citations
from arp.normalise.value import typed_value
from arp.schemas.common import DocumentChunk, SourceDocument
from arp.schemas.datapoints import ExtractedField, FieldDefinition, ValueState
from arp.schemas.review import ReasonCode


def build_extracted_fields(
    field: FieldDefinition,
    draft: ExtractionDraft,
    verifier: VerifierOutput,
    documents_by_id: dict[str, SourceDocument],
    fuzzy_threshold: float,
    confidence_review_threshold: float,
    *,
    passages: dict[str, DocumentChunk] | None = None,
    fiscal_year_end: str | None = None,
) -> list[ExtractedField]:
    """Merges the extractor draft and the independent verifier pass into one
    ExtractedField per reported period (latest period first), applying the
    hard programmatic grounding check to each value on top of both LLM
    opinions. An entry needs review when it has any review_reasons.
    """
    values = draft.values
    if not values:
        if verifier.agrees:
            f, _ = no_evidence_field(field)
            # Nothing claimed, nothing to ground (as before typed values).
            return [f.model_copy(update={"grounded": True, "verifier_notes": "The extractor found no disclosed value."})]
        # The verifier says a value exists: keep that claim visible (ungrounded) for review.
        values = [PeriodValue(state=ValueState.NOT_FOUND)]

    typed = [(pv, typed_value(field, pv, fiscal_year_end=fiscal_year_end)) for pv in values]
    typed.sort(key=lambda t: t[1].period_end or "", reverse=True)  # ISO dates sort as text; None ("") last

    kept: dict[str, list] = {}
    for pv, tv in typed:
        key = tv.period_end or "unspecified"
        if key in kept:
            kept[key][2] = True  # a second value for the same period
        else:
            kept[key] = [pv, tv, False]

    out: list[ExtractedField] = []
    for i, (pv, tv, duplicated) in enumerate(kept.values()):
        claimed = tv.value_state != ValueState.NOT_FOUND
        disagrees_here = i == 0 and not verifier.agrees
        if disagrees_here:
            # VerifierOutput carries no citations of its own -- pv.citations
            # supported the value the verifier just rejected, so they can't
            # back verifier.corrected_value. A real corrected value with
            # nothing behind it is explicitly not grounded.
            tv = typed_value(field, pv.model_copy(update={"value": verifier.corrected_value, "state": ValueState.FOUND}),
                             fiscal_year_end=fiscal_year_end)
            final_citations = []
        else:
            final_citations = ground_citations(pv.citations, documents_by_id, fuzzy_threshold, passages=passages)
        has_value = tv.value_state != ValueState.NOT_FOUND
        all_grounded = all(c.grounded for c in final_citations) if final_citations else not has_value

        final_confidence = min(draft.confidence, verifier.confidence) if claimed else 0.0

        notes_parts: list[str] = []
        if not verifier.agrees:
            notes_parts.append(f"Verifier disagreed with the extractor: {verifier.notes}")
        elif verifier.notes:
            notes_parts.append(verifier.notes)
        if has_value and not all_grounded:
            if final_citations:
                notes_parts.append("One or more citations failed the programmatic grounding check.")
            else:
                notes_parts.append("No grounded citation supports this value.")
        if duplicated:
            notes_parts.append("The extractor reported more than one value for this period; the first is kept.")
        notes_parts.extend(tv.notes)

        conflict = bool(draft.conflicting_sources) or duplicated
        reasons = [
            code
            for code, applies in (
                (ReasonCode.NOT_GROUNDED, has_value and not all_grounded),
                (ReasonCode.VERIFIER_DISAGREES, not verifier.agrees),
                (ReasonCode.CONFLICT, conflict),
                (ReasonCode.LOW_CONFIDENCE, claimed and final_confidence < confidence_review_threshold),
            )
            if applies
        ]
        reasons += [r for r in tv.reasons if r not in reasons]

        out.append(
            ExtractedField(
                field_id=field.field_id,
                field_name=field.name,
                value=tv.value,
                raw_value_text=pv.raw_value_text,
                citations=final_citations,
                confidence=final_confidence,
                grounded=all_grounded,
                verifier_notes=" ".join(notes_parts).strip() or None,
                conflicting_sources=conflict,
                review_reasons=reasons,
                value_state=tv.value_state,
                unit=tv.unit,
                canonical_value=tv.canonical_value,
                canonical_unit=tv.canonical_unit,
                scale_applied=tv.scale_applied,
                period_text=tv.period_text,
                period_start=tv.period_start,
                period_end=tv.period_end,
                basis=tv.basis,
                qualifiers=tv.qualifiers,
                reported_precision=tv.reported_precision,
                fx_rate=tv.fx_rate,
                fx_rate_ref=tv.fx_rate_ref,
            )
        )
    return out


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
            value_state=ValueState.NOT_FOUND,
            confidence=0.0,
            grounded=False,
            verifier_notes="No evidence matching this field's keywords was found in the available documents.",
        ),
        False,
    )
