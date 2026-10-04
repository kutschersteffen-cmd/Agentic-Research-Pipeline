"""E40: a third, adjudicating call only on a typed disagreement; its value is
kept only with a grounded citation."""

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
_FIELD = FieldDefinition(
    name="revenue_usd_m", description="Total revenue.", data_type=FieldDataType.CURRENCY_AMOUNT, unit="USD millions",
    extraction_instructions="Total revenue for the fiscal year.", seed_keywords=["revenues"],
)
_GOOD = "Total revenues were $383,285 million"


def _cite(quote: str) -> list[Citation]:
    return [Citation(doc_id=_DOC.doc_id, doc_type=_DOC.doc_type, quote=quote)]


# The extractor misread the scale but cites a real (grounded) passage.
_DRAFT = ExtractionDraft(
    values=[PeriodValue(value=383.285, raw_value_text="383.285", unit_text="USD million", period_text="fiscal 2024",
                        citations=_cite("Acme Corp annual report 2024"))],
    confidence=0.9,
)


def _verifier(agrees=False, kind=DisagreementType.VALUE, value=390000.0, citations=()):
    return VerifierOutput(agrees=agrees, corrected_value=value, confidence=0.8, notes="checked",
                          disagreement_type=kind, citations=list(citations))


class _ModelNamed:
    """Wraps a fake client so its usages carry a model name (provenance)."""

    def __init__(self, inner, model):
        self.inner, self.model = inner, model

    async def complete_structured(self, **kw):
        out, usage = await self.inner.complete_structured(**kw)
        return out, usage.model_copy(update={"model": self.model})


async def _run(fake_llm, verifier_output, adjudicator_outputs=()):
    extractor = fake_llm({"ExtractionDraft": [_DRAFT]})
    verifier = fake_llm({"VerifierOutput": [verifier_output], "AdjudicatorOutput": list(adjudicator_outputs)})
    fields, _, usages = await extract_one_field(
        "Acme Corp", _FIELD, documents=[_DOC], documents_by_id={_DOC.doc_id: _DOC}, llm=extractor,
        verifier_llm=_ModelNamed(verifier, "second-model"), fuzzy_threshold=0.92, confidence_review_threshold=0.5,
    )
    return fields, usages, extractor, verifier


@pytest.mark.parametrize("kind", [DisagreementType.NONE, DisagreementType.VALUE], ids=["plain", "agrees_but_typed"])
async def test_adjudicator_not_called_when_verifier_agrees(fake_llm, kind):
    # agrees=True wins over a contradicting type: no disagreement, no third call.
    (f,), usages, _, verifier = await _run(fake_llm, _verifier(agrees=True, kind=kind, value=None))
    assert verifier.calls.count("AdjudicatorOutput") == 0
    assert len(usages) == 2
    assert f.provenance.adjudicator_model is None


@pytest.mark.parametrize(
    "verifier_output",
    [_verifier(), _verifier(kind=DisagreementType.NONE), _verifier(kind=DisagreementType.PERIOD, value=None)],
    ids=["value", "disagrees_but_type_none", "period_no_offer"],
)
async def test_typed_disagreement_calls_adjudicator_once(fake_llm, verifier_output):
    unsettled = AdjudicatorOutput(settled=False, value=None, citations=[], notes="cannot tell")
    _, _, extractor, verifier = await _run(fake_llm, verifier_output, [unsettled])
    assert extractor.calls == ["ExtractionDraft"]
    assert verifier.calls == ["VerifierOutput", "AdjudicatorOutput"]
    prompt = verifier.prompts[1]
    assert "values[0]" in prompt and verifier_output.notes in prompt
    # A disagreeing verifier that typed it "none" is a value disagreement.
    expected = DisagreementType.VALUE if verifier_output.disagreement_type == DisagreementType.NONE else \
        verifier_output.disagreement_type
    assert f"disagreement_type: {expected.value}" in prompt


async def test_settled_with_grounded_citation_sets_value(fake_llm):
    settled = AdjudicatorOutput(settled=True, value=383285.0, citations=_cite(_GOOD) + _cite("not in the text"),
                                notes="the table states millions")
    (f,), _, _, _ = await _run(fake_llm, _verifier(), [settled])  # verifier's 390000 is uncited
    assert f.value == 383285.0
    assert f.method == "adjudicated"
    assert [c.quote for c in f.citations] == [_GOOD] and f.grounded
    assert f.provenance.adjudicator_model == "second-model"
    assert sorted(a.source for a in f.alternatives) == ["extractor", "verifier"]
    assert ReasonCode.ADJUDICATOR_UNRESOLVED not in f.review_reasons
    assert ReasonCode.VERIFIER_CORRECTION_UNCITED not in f.review_reasons
    assert ReasonCode.VERIFIER_DISAGREES not in f.review_reasons  # the adjudicator settled it


@pytest.mark.parametrize(
    "adjudication",
    [AdjudicatorOutput(settled=False, value=None, citations=_cite(_GOOD), notes="unclear"),
     AdjudicatorOutput(settled=True, value=383285.0, citations=[], notes="trust me"),
     AdjudicatorOutput(settled=True, value=383285.0, citations=_cite("Revenues were 383,285"), notes="misquoted")],
    ids=["unsettled", "settled_uncited", "settled_ungrounded"],
)
async def test_unsettled_or_uncited_goes_to_review(fake_llm, adjudication):
    (f,), _, _, _ = await _run(fake_llm, _verifier(), [adjudication])
    assert f.value == 383.285  # the extractor's value stays
    assert f.method == "extracted"
    assert ReasonCode.ADJUDICATOR_UNRESOLVED in f.review_reasons
    assert {(a.source, a.value) for a in f.alternatives} == {("extractor", 383.285), ("verifier", 390000.0)}


async def test_adjudicator_usage_counted_in_cost(fake_llm):
    unsettled = AdjudicatorOutput(settled=False, value=None, citations=[], notes="cannot tell")
    _, usages, _, _ = await _run(fake_llm, _verifier(), [unsettled])
    assert len(usages) == 3
    assert usages[2].model == "second-model"


def test_no_correction_offered_is_not_a_rejected_correction():
    # A period disagreement with nothing to offer: no "correction rejected" signal.
    verifier = _verifier(kind=DisagreementType.PERIOD, value=None)
    (f,) = build_extracted_fields(_FIELD, _DRAFT, verifier, {_DOC.doc_id: _DOC}, 0.92, 0.5)
    assert f.value == 383.285
    assert ReasonCode.VERIFIER_DISAGREES in f.review_reasons
    assert ReasonCode.VERIFIER_CORRECTION_UNCITED not in f.review_reasons
    assert f.alternatives == []
