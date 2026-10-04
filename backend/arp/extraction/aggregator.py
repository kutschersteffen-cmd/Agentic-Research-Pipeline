from __future__ import annotations

from dataclasses import replace

from arp.extraction.adjudicator import AdjudicatorOutput
from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue
from arp.extraction.verifier_agent import VerifierOutput
from arp.grounding import ground_citations
from arp.normalise.locale import Decimal, citation_decimal
from arp.normalise.value import NUMERIC, typed_value
from arp.schemas.common import DocumentChunk, SourceDocument
from arp.schemas.datapoints import Alternative, ExtractedField, FieldDefinition, ValueState
from arp.schemas.review import ReasonCode


def _decimal(
    pv: PeriodValue, documents_by_id: dict[str, SourceDocument], fuzzy_threshold: float,
    passages: dict[str, DocumentChunk] | None,
) -> Decimal | None:
    cits = pv.citations
    if any(d.table_spans for c in cits if (d := documents_by_id.get(c.doc_id))):
        # ponytail: grounds these citations a second time (only for documents with tables); hoist if it shows in profiles.
        cits = ground_citations(cits, documents_by_id, fuzzy_threshold, passages=passages)
    return citation_decimal(cits, documents_by_id)


def _taken(tv, v, what: str):
    """`tv` with a value another call supplied. The draft's raw/unit text no
    longer describes it, so nothing is converted from that text."""
    zero = isinstance(v, (int, float)) and not isinstance(v, bool) and v == 0
    state = ValueState.NOT_FOUND if v is None else ValueState.ZERO if zero else ValueState.FOUND
    return replace(
        tv, value=v, value_state=state, canonical_value=None, canonical_unit=None, scale_applied=None,
        fx_rate=None, fx_rate_ref=None, reasons=[],
        notes=[f"No canonical value is computed for the {what}."] if v is not None else [],
    )


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
    adjudicator: AdjudicatorOutput | None = None,
) -> list[ExtractedField]:
    """Merges the extractor draft and the independent verifier pass into one
    ExtractedField per reported period (latest period first), applying the
    hard programmatic grounding check to each value on top of both LLM
    opinions. An entry needs review when it has any review_reasons.
    `adjudicator`, when the third call ran, settles values[0] only with a
    grounded citation.
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

    def _typed(pv: PeriodValue):
        dec = _decimal(pv, documents_by_id, fuzzy_threshold, passages)  # disagreeing or unknown -> flag ambiguity
        return typed_value(field, pv, fiscal_year_end=fiscal_year_end, planned=planned, decimal=dec)

    typed = [(pv, _typed(pv)) for pv in values]
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
        def _placed(tv):
            if unresolved and tv.period_end is None:
                return replace(tv, reasons=[*tv.reasons, ReasonCode.CHECK_FAILED],
                               notes=[*tv.notes, f"period not resolved: {tv.period_text or '(none)'}"])
            return tv

        tv = _placed(tv)
        claimed = tv.value_state != ValueState.NOT_FOUND
        first = pv is values[0]
        # The verifier's corrected_value is for values[0] as it saw them (draft
        # order); the stable sort keeps that entry first in its period group.
        # A disagreement with nothing offered (no value, no citation) is no correction.
        correction = first and not verifier.agrees and (verifier.corrected_value is not None or bool(verifier.citations))
        cited = (
            ground_citations(verifier.citations, documents_by_id, fuzzy_threshold, passages=passages)
            if correction else []
        )
        cited_correction = correction and any(c.grounded for c in cited)
        # E40: the adjudicator's value is kept only with a grounded citation.
        adj = adjudicator if first else None
        adj_cited = ground_citations(adj.citations, documents_by_id, fuzzy_threshold, passages=passages) if adj else []
        settled = adj is not None and adj.settled and any(c.grounded for c in adj_cited)
        adj_unresolved = adj is not None and not settled
        # E38: a correction with no grounded citation never becomes the value;
        # the extractor's value stays and the correction waits for review.
        uncited = correction and not cited_correction and not settled
        extractor_citations = ground_citations(pv.citations, documents_by_id, fuzzy_threshold, passages=passages)
        if claimed and (settled or adj_unresolved or cited_correction):
            alternatives.append(Alternative(
                value=tv.value, raw_value_text=pv.raw_value_text, source="extractor", citations=extractor_citations,
            ))
        if correction and (settled or adj_unresolved or uncited):
            alternatives.append(Alternative(value=verifier.corrected_value, source="verifier", citations=cited))
        if adj_unresolved and adj.value is not None:  # its figure, uncited or ungrounded, is a reviewer's suggestion
            alternatives.append(Alternative(
                value=adj.value, raw_value_text=adj.raw_value_text, source="adjudicator", citations=adj_cited,
            ))
        if settled:
            # Typed like an extracted value (same period, the adjudicator's figure,
            # unit and citations), so its canonical value is computed and checked.
            final_citations = [c for c in adj_cited if c.grounded]
            pv = pv.model_copy(update={
                "value": adj.value, "state": ValueState.NOT_FOUND if adj.value is None else ValueState.FOUND,
                "raw_value_text": adj.raw_value_text, "unit_text": adj.unit_text, "citations": final_citations,
            })
            tv = _placed(_typed(pv))
        elif cited_correction:
            # pv.citations supported the value the verifier just rejected, so
            # the verifier's own grounded citations back the correction.
            tv = _taken(tv, verifier.corrected_value, "verifier's correction")
            final_citations = cited
        else:
            final_citations = extractor_citations
        for d in dupes.get(key, []):
            dtv = _typed(d)
            if dtv.value_state != ValueState.NOT_FOUND:
                alternatives.append(Alternative(
                    value=dtv.value, raw_value_text=d.raw_value_text, source="duplicate",
                    citations=ground_citations(d.citations, documents_by_id, fuzzy_threshold, passages=passages),
                ))
        has_value = tv.value_state != ValueState.NOT_FOUND
        all_grounded = all(c.grounded for c in final_citations) if final_citations else not has_value

        final_confidence = min(draft.confidence, verifier.confidence) if claimed else 0.0

        notes_parts: list[str] = []
        if not verifier.agrees:
            notes_parts.append(f"Verifier disagreed with the extractor: {verifier.notes}")
        elif verifier.notes:
            notes_parts.append(verifier.notes)
        if settled:
            notes_parts.append(f"The adjudicator settled the disagreement: {adj.notes}")
        elif adj_unresolved:
            notes_parts.append(f"The adjudicator did not settle the disagreement with a grounded citation: {adj.notes}")
        if uncited:
            notes_parts.append("The verifier's correction has no grounded citation; the extractor's value is kept.")
        if has_value and not all_grounded:
            if final_citations:
                notes_parts.append("One or more citations failed the programmatic grounding check.")
            else:
                notes_parts.append("No grounded citation supports this value.")
        if duplicated:
            notes_parts.append("The extractor reported more than one value for this period; the first is kept.")
        notes_parts.extend(tv.notes)

        conflict = bool(draft.conflicting_sources) or duplicated
        # A settled disagreement leaves review only on a low-risk field whose value
        # converted to the field's unit (an off-scale figure fails that conversion).
        auto_accept = not field.high_risk and (field.data_type not in NUMERIC or tv.canonical_value is not None)
        reasons = [
            code
            for code, applies in (
                (ReasonCode.NOT_GROUNDED, has_value and not all_grounded),
                (ReasonCode.VERIFIER_DISAGREES, not verifier.agrees and not (settled and auto_accept)),
                (ReasonCode.VERIFIER_CORRECTION_UNCITED, uncited),
                (ReasonCode.ADJUDICATOR_UNRESOLVED, adj_unresolved),
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
                method="adjudicated" if settled else "extracted",
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
