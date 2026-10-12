from arp.extraction.extractor_agent import ExtractionDraft
from arp.extraction.field_graph import extract_one_field
from arp.schemas.common import DocType, SourceDocument
from arp.schemas.datapoints import FieldDataType, FieldDefinition

_DOC = SourceDocument(company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG", full_text="We sell shoes.")


async def _run(fake_llm, *, high_risk):
    field = FieldDefinition(
        name="f", description="d", data_type=FieldDataType.NUMBER, extraction_instructions="look",
        seed_keywords=["zzzunmatched"], high_risk=high_risk,
    )
    # a high-risk field's verifier is a blind second extraction, so it needs its own draft
    llm = fake_llm({"ExtractionDraft": [ExtractionDraft(confidence=0.0)] * 2})
    await extract_one_field(
        "Acme", field, documents=[_DOC], documents_by_id={_DOC.doc_id: _DOC}, llm=llm, verifier_llm=llm,
        fuzzy_threshold=0.9, confidence_review_threshold=0.6,
    )
    return llm


async def test_high_risk_field_still_extracts_when_no_keyword_hits(fake_llm):
    assert "ExtractionDraft" in (await _run(fake_llm, high_risk=True)).calls


async def test_low_risk_field_skips_extraction_when_no_keyword_hits(fake_llm):
    assert (await _run(fake_llm, high_risk=False)).calls == []
