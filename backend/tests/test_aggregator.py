from arp.extraction.aggregator import build_extracted_field
from arp.extraction.extractor_agent import ExtractionDraft
from arp.extraction.verifier_agent import VerifierOutput
from arp.schemas.datapoints import FieldDataType, FieldDefinition

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

    field_result, needs_review = build_extracted_field(_FIELD, draft, verifier, {}, fuzzy_threshold=0.9, confidence_review_threshold=0.6)

    assert field_result.value == 42.5
    assert field_result.grounded is False
    assert field_result.citations == []
    assert needs_review is True


def test_verifier_agreement_with_no_citations_and_no_value_is_grounded():
    # "Not found" reported by both extractor and verifier: nothing to
    # ground, so this is trivially grounded (not a missing-citations bug).
    draft = ExtractionDraft(value=None, citations=[], confidence=0.9)
    verifier = VerifierOutput(agrees=True, confidence=0.9, notes="Agreed: not disclosed.")

    field_result, needs_review = build_extracted_field(_FIELD, draft, verifier, {}, fuzzy_threshold=0.9, confidence_review_threshold=0.6)

    assert field_result.value is None
    assert field_result.grounded is True
    assert needs_review is False
