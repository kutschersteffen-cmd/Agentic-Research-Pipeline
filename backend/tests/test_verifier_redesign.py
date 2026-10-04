"""E38: high-risk fields verify blind, disagreements are typed in code, and a
correction only replaces a value when it carries a grounded citation."""

import pytest

from arp.extraction.adjudicator import AdjudicatorOutput
from arp.extraction.aggregator import build_extracted_fields
from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue
from arp.extraction.field_graph import extract_one_field
from arp.extraction.verifier_agent import DisagreementType, VerifierOutput
from arp.schemas.common import Citation, DocType, SourceDocument
from arp.schemas.datapoints import FieldDataType, FieldDefinition
from arp.schemas.review import ReasonCode

_TEXT = "Acme Corp annual report 2024. Total revenues were $383,285 million in fiscal 2024."
_DOC = SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="Annual report 2024", full_text=_TEXT)
_PLANNED = ["2024-12-31"]


def _field(high_risk: bool) -> FieldDefinition:
    return FieldDefinition(
        name="revenue_usd_m", description="Total revenue.", data_type=FieldDataType.CURRENCY_AMOUNT, unit="USD millions",
        extraction_instructions="Total revenue for the fiscal year.", seed_keywords=["revenues"], high_risk=high_risk,
    )


def _cite(quote: str) -> list[Citation]:
    return [Citation(doc_id=_DOC.doc_id, doc_type=_DOC.doc_type, quote=quote)]


def _draft(value: float, unit: str = "USD million", quote: str = "Total revenues were $383,285 million") -> ExtractionDraft:
    return ExtractionDraft(
        values=[PeriodValue(value=value, raw_value_text=f"{value}", unit_text=unit, period_text="fiscal 2024",
                            citations=_cite(quote))],
        confidence=0.9,
    )


def _build(draft, verifier):
    return build_extracted_fields(
        _field(False), draft, verifier, {_DOC.doc_id: _DOC}, fuzzy_threshold=0.92, confidence_review_threshold=0.5,
    )


@pytest.mark.parametrize("citations", [[], _cite("Total revenues were $390,000 million")], ids=["none", "not_in_text"])
def test_correction_without_citation_is_rejected(citations):
    draft = _draft(383285.0)
    verifier = VerifierOutput(agrees=False, corrected_value=390000.0, confidence=0.8, notes="misread",
                              disagreement_type=DisagreementType.VALUE, citations=citations)
    (f,) = _build(draft, verifier)
    assert f.value == 383285.0
    assert f.grounded is True
    assert ReasonCode.VERIFIER_CORRECTION_UNCITED in f.review_reasons
    (alt,) = [a for a in f.alternatives if a.source == "verifier"]
    assert alt.value == 390000.0


def test_grounded_correction_replaces_value():
    draft = _draft(383.285, quote="Acme Corp annual report 2024")  # the extractor's own citation is beside the point
    verifier = VerifierOutput(agrees=False, corrected_value=383285.0, confidence=0.8, notes="scale",
                              disagreement_type=DisagreementType.UNIT_OR_SCALE,
                              citations=_cite("Total revenues were $383,285 million"))
    (f,) = _build(draft, verifier)
    assert f.value == 383285.0
    assert [c.quote for c in f.citations] == ["Total revenues were $383,285 million"]
    assert all(c.grounded for c in f.citations)
    assert ReasonCode.VERIFIER_CORRECTION_UNCITED not in f.review_reasons
    assert [a.source for a in f.alternatives] == ["extractor"]


async def _run(field, extractor, verifier):
    return await extract_one_field(
        "Acme Corp", field, documents=[_DOC], documents_by_id={_DOC.doc_id: _DOC}, llm=extractor, verifier_llm=verifier,
        fuzzy_threshold=0.92, confidence_review_threshold=0.5, planned_periods=_PLANNED,
    )


@pytest.mark.parametrize(
    ("blind", "expected"),
    [(_draft(390000.0, quote="Total revenues were $383,285 million"), DisagreementType.VALUE),
     (_draft(383285.0, unit="USD thousands"), DisagreementType.UNIT_OR_SCALE)],
    ids=["value", "scale"],
)
async def test_high_risk_field_verifies_blind(fake_llm, blind, expected):
    extractor = fake_llm({"ExtractionDraft": [_draft(383285.0)]})
    unsettled = AdjudicatorOutput(settled=False, notes="cannot tell")
    verifier = fake_llm({"ExtractionDraft": [blind], "AdjudicatorOutput": [unsettled]})
    (f,), _, _ = await _run(_field(True), extractor, verifier)

    assert verifier.calls == ["ExtractionDraft", "AdjudicatorOutput"]  # a re-extraction, not the review prompt
    assert repr(383285.0) not in verifier.prompts[0]
    assert "values[0]" not in verifier.prompts[0]
    assert ReasonCode.VERIFIER_DISAGREES in f.review_reasons
    # The blind value carries its own (grounded) citation, so it replaces the draft's.
    assert f.value == blind.values[0].value

    from arp.extraction.verifier_agent import blind_verify

    out, _ = await blind_verify("Acme Corp", _field(True), [], _draft(383285.0), fake_llm({"ExtractionDraft": [blind]}),
                                _PLANNED)
    assert out.disagreement_type == expected
    assert out.agrees is False
    assert out.corrected_value == blind.values[0].value
    assert out.citations == blind.values[0].citations


async def test_low_risk_field_uses_review_prompt(fake_llm):
    extractor = fake_llm({"ExtractionDraft": [_draft(383285.0)]})
    verifier = fake_llm({"VerifierOutput": [VerifierOutput(agrees=True, confidence=0.9, notes="ok")]})
    (f,), _, _ = await _run(_field(False), extractor, verifier)
    assert verifier.calls == ["VerifierOutput"]
    assert "values[0]" in verifier.prompts[0]
    assert f.value == 383285.0


async def test_verifier_agreement_has_type_none(fake_llm):
    assert VerifierOutput(agrees=True, confidence=0.9, notes="").disagreement_type == DisagreementType.NONE

    from arp.extraction.verifier_agent import blind_verify

    # The same amount stated in thousands is no disagreement.
    blind = _draft(383285000.0, unit="USD thousands")
    out, _ = await blind_verify("Acme Corp", _field(True), [], _draft(383285.0), fake_llm({"ExtractionDraft": [blind]}),
                                _PLANNED)
    assert out.agrees is True
    assert out.disagreement_type == DisagreementType.NONE
    assert out.corrected_value is None
    assert out.citations == []
