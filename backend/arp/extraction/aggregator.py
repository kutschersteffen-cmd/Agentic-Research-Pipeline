from __future__ import annotations

from dataclasses import replace

from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue
from arp.extraction.verifier_agent import VerifierOutput
from arp.grounding import ground_citations
from arp.normalise.value import typed_value
from arp.schemas.common import DocumentChunk, SourceDocument
from arp.schemas.datapoints import Alternative, ExtractedField, FieldDefinition, ValueState
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
    planned_periods: list[str] | None = None,
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

    planned = set(planned_periods or ())
    typed = [(pv, typed_value(field, pv, fiscal_year_end=fiscal_year_end, planned=planned)) for pv in values]
    typed.sort(key=lambda t: t[1].period_end or "", reverse=True)  # ISO dates sort as text; None ("") last

    kept: dict[str, list] = {}
    dupes: dict[str, list[PeriodValue]] = {}
    for pv, tv in typed:
        # Unresolved periods with different labels are different periods we can't place, not duplicates.
        key = tv.period_end or f"unspecified:{tv.period_text or ''}"
        if key in kept:
            kept[key][2] = True  # a second value for the same period
            dupes.setdefault(key, []).append(pv)
        else:
            kept[key] = [pv, tv, False]

    unresolved = sum(1 for _, tv, _ in kept.values() if tv.period_end is None) > 1
    out: list[ExtractedField] = []
    for key, (pv, tv, duplicated) in kept.items():
        alternatives: list[Alternative] = []
        if unresolved and tv.period_end is None:
            tv = replace(tv, reasons=[*tv.reasons, ReasonCode.CHECK_FAILED],
                         notes=[*tv.notes, f"period not resolved: {tv.period_text or '(none)'}"])
        claimed = tv.value_state != ValueState.NOT_FOUND
        # The verifier's corrected_value is for values[0] as it saw them (draft
        # order); the stable sort keeps that entry first in its period group.
        if pv is values[0] and not verifier.agrees:
            # VerifierOutput carries no citations of its own -- pv.citations
            # supported the value the verifier just rejected, so they can't
            # back verifier.corrected_value. A real corrected value with
            # nothing behind it is explicitly not grounded. The rejected
            # raw/unit text no longer describes the value, so nothing is
            # converted from it.
            v = verifier.corrected_value
            if tv.value_state != ValueState.NOT_FOUND:  # nothing claimed, nothing to keep
                alternatives.append(Alternative(
                    value=tv.value, raw_value_text=pv.raw_value_text, source="extractor",
                    citations=ground_citations(pv.citations, documents_by_id, fuzzy_threshold, passages=passages),
                ))
            zero = isinstance(v, (int, float)) and not isinstance(v, bool) and v == 0
            state = ValueState.NOT_FOUND if v is None else ValueState.ZERO if zero else ValueState.FOUND
            tv = replace(
                tv, value=v, value_state=state, canonical_value=None, canonical_unit=None, scale_applied=None,
                fx_rate=None, fx_rate_ref=None, reasons=[],
                notes=["No canonical value is computed for the verifier's correction."] if v is not None else [],
            )
            final_citations = []
        else:
            final_citations = ground_citations(pv.citations, documents_by_id, fuzzy_threshold, passages=passages)
        alternatives += [
            Alternative(
                value=typed_value(field, d, fiscal_year_end=fiscal_year_end, planned=planned).value,
                raw_value_text=d.raw_value_text, source="duplicate",
                citations=ground_citations(d.citations, documents_by_id, fuzzy_threshold, passages=passages),
            )
            for d in dupes.get(key, [])
        ]
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
                extractor_confidence=draft.confidence,
                verifier_confidence=verifier.confidence,
                alternatives=alternatives,
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
