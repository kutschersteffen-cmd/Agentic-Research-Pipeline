from arp.extraction.aggregator import build_extracted_fields, no_evidence_field
from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue
from arp.extraction.verifier_agent import VerifierOutput
from arp.schemas.common import Citation, DocType, SourceDocument
from arp.schemas.datapoints import ExtractedField, FieldDataType, FieldDefinition, ValueState
from arp.schemas.review import ReasonCode

_FIELD = FieldDefinition(
    name="Green CapEx",
    description="Capital expenditure directed at green/sustainable initiatives.",
    data_type=FieldDataType.NUMBER,
    extraction_instructions="Look in the sustainability report.",
)


def test_verifier_override_of_null_value_is_not_shown_as_grounded():
    # Extractor correctly found nothing (value=None, no citations); verifier
    # disagrees and supplies a real number with no citations of its own --
    # the merged field must not claim that number is grounded.
    draft = ExtractionDraft(value=None, citations=[], confidence=0.8)
    verifier = VerifierOutput(agrees=False, corrected_value=42.5, confidence=0.7, notes="Found it on page 12.")

    (field_result,) = build_extracted_fields(_FIELD, draft, verifier, {}, fuzzy_threshold=0.9, confidence_review_threshold=0.6)
    needs_review = bool(field_result.review_reasons)

    assert field_result.value == 42.5
    assert field_result.grounded is False
    assert field_result.citations == []
    assert needs_review is True


def test_verifier_agreement_with_no_citations_and_no_value_is_grounded():
    # "Not found" reported by both extractor and verifier: nothing to
    # ground, so this is trivially grounded (not a missing-citations bug).
    draft = ExtractionDraft(value=None, citations=[], confidence=0.9)
    verifier = VerifierOutput(agrees=True, confidence=0.9, notes="Agreed: not disclosed.")

    (field_result,) = build_extracted_fields(_FIELD, draft, verifier, {}, fuzzy_threshold=0.9, confidence_review_threshold=0.6)
    needs_review = bool(field_result.review_reasons)

    assert field_result.value is None
    assert field_result.grounded is True
    assert needs_review is False


def _build_all(draft, verifier, docs=None, **kw):
    return build_extracted_fields(_FIELD, draft, verifier, docs or {}, fuzzy_threshold=0.9, confidence_review_threshold=0.6, **kw)


def _build(draft, verifier, docs=None):
    (field_result,) = _build_all(draft, verifier, docs)
    return field_result, bool(field_result.review_reasons)


def test_reasons_for_ungrounded_value():
    draft = ExtractionDraft(value=1.0, citations=[], confidence=0.9)
    field_result, needs_review = _build(draft, VerifierOutput(agrees=True, confidence=0.9, notes=""))
    assert field_result.review_reasons == [ReasonCode.NOT_GROUNDED]
    assert needs_review is True


def test_reasons_for_verifier_disagreement_and_conflict():
    draft = ExtractionDraft(value=1.0, citations=[], confidence=0.9, conflicting_sources=True)
    verifier = VerifierOutput(agrees=False, corrected_value=None, confidence=0.9, notes="no")
    field_result, _ = _build(draft, verifier)
    assert field_result.review_reasons == [ReasonCode.VERIFIER_DISAGREES, ReasonCode.CONFLICT]


def test_no_reasons_means_no_review():
    draft = ExtractionDraft(value=None, citations=[], confidence=0.9)
    field_result, needs_review = _build(draft, VerifierOutput(agrees=True, confidence=0.9, notes=""))
    assert field_result.review_reasons == []
    assert needs_review is False


_DOC = SourceDocument(
    company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG",
    full_text="Scope 1 emissions were 120 tonnes in FY2024 and 100 tonnes in FY2023. Spills: 0 incidents in FY2024.",
)
_AGREE = VerifierOutput(agrees=True, confidence=0.9, notes="")


def _cite(quote):
    return [Citation(doc_id=_DOC.doc_id, doc_type=_DOC.doc_type, quote=quote)]


def test_zero_and_not_found_stay_distinct():
    zero = ExtractionDraft(
        values=[PeriodValue(value=0, state="zero", raw_value_text="0", citations=_cite("Spills: 0 incidents in FY2024"))],
        confidence=0.9,
    )
    (f,) = _build_all(zero, _AGREE, {_DOC.doc_id: _DOC})
    assert f.value_state == "zero" and f.value == 0
    assert f.grounded is True and f.review_reasons == []

    (nf,) = _build_all(ExtractionDraft(values=[], confidence=0.9), _AGREE)
    assert nf.value_state == "not_found" and nf.value is None
    assert nf.verifier_notes == "The extractor found no disclosed value."


def test_no_evidence_field_is_not_found():
    f, needs_review = no_evidence_field(_FIELD)
    assert f.value_state == ValueState.NOT_FOUND and f.value is None and needs_review is False


def test_multi_period_one_field_each_latest_first():
    draft = ExtractionDraft(
        values=[
            PeriodValue(value=100.0, raw_value_text="100", unit_text="tonnes", period_text="FY2023",
                        citations=_cite("100 tonnes in FY2023")),
            PeriodValue(value=120.0, raw_value_text="120", unit_text="tonnes", period_text="FY2024",
                        citations=_cite("120 tonnes in FY2024")),
        ],
        confidence=0.9,
    )
    fields = _build_all(draft, _AGREE, {_DOC.doc_id: _DOC}, fiscal_year_end=None)
    assert [f.period_end for f in fields] == ["2024-12-31", "2023-12-31"]
    assert [f.value for f in fields] == [120.0, 100.0]
    assert all("fiscal_year_end_assumed" in f.qualifiers for f in fields)
    assert all(f.grounded and f.review_reasons == [] for f in fields)


def test_verifier_disagreement_replaces_first_sorted_entry_only():
    draft = ExtractionDraft(
        values=[
            PeriodValue(value=100.0, period_text="FY2023", citations=_cite("100 tonnes in FY2023")),
            PeriodValue(value=999.0, period_text="FY2024", citations=_cite("120 tonnes in FY2024")),
        ],
        confidence=0.9,
    )
    verifier = VerifierOutput(agrees=False, corrected_value=120.0, confidence=0.9, notes="misread")
    latest, older = _build_all(draft, verifier, {_DOC.doc_id: _DOC})
    assert (latest.value, latest.citations, latest.grounded) == (120.0, [], False)
    assert latest.review_reasons == [ReasonCode.NOT_GROUNDED, ReasonCode.VERIFIER_DISAGREES]
    assert older.value == 100.0 and older.grounded is True
    assert older.review_reasons == [ReasonCode.VERIFIER_DISAGREES]


def test_duplicate_period_values_flag_conflict():
    draft = ExtractionDraft(
        values=[
            PeriodValue(value=120.0, period_text="FY2024", citations=_cite("120 tonnes in FY2024")),
            PeriodValue(value=100.0, period_text="FY2024", citations=_cite("100 tonnes in FY2023")),
        ],
        confidence=0.9,
    )
    (f,) = _build_all(draft, _AGREE, {_DOC.doc_id: _DOC}, fiscal_year_end="12-31")
    assert f.value == 120.0
    assert f.review_reasons == [ReasonCode.CONFLICT]


def test_legacy_draft_shape_still_validates():
    draft = ExtractionDraft(value=42.0, raw_value_text="42", citations=_cite("120 tonnes"), confidence=0.9)
    (pv,) = draft.values
    assert (pv.value, pv.raw_value_text, pv.state) == (42.0, "42", ValueState.FOUND)
    assert pv.citations[0].quote == "120 tonnes"
    assert ExtractionDraft.model_validate({"value": None, "citations": [], "confidence": 0}).values == []


def test_old_extracted_field_row_loads():
    base = {"field_id": "f", "field_name": "F", "confidence": 0}
    assert ExtractedField.model_validate({**base, "value": None}).value_state == "not_found"
    assert ExtractedField.model_validate({**base, "value": 3.2}).value_state == "found"
    assert ExtractedField.model_validate({**base, "value": 0}).value_state == "zero"
    assert ExtractedField.model_validate({**base, "value": False}).value_state == "found"
    assert ExtractedField.model_validate({**base, "value": None, "value_state": "not_applicable"}).value_state == "not_applicable"


def test_period_key():
    from arp.schemas.review import period_key

    assert period_key({"period_end": "2024-12-31"}) == "2024-12-31"
    assert period_key({"field_id": "f"}) == "unspecified"
    assert period_key(ExtractedField(field_id="f", field_name="F", value=None, confidence=0)) == "unspecified"
