from arp.extraction.aggregator import build_extracted_fields
from arp.extraction.extractor_agent import BOOLEAN_RULE, ExtractionDraft, PeriodValue, extract_field, format_evidence
from arp.extraction.verifier_agent import VerifierOutput
from arp.schemas.common import DocType, DocumentChunk
from arp.schemas.datapoints import FieldDataType, FieldDefinition
from arp.schemas.review import ReasonCode


def _chunk(**kw):
    return DocumentChunk(chunk_id="p1", doc_id="d1", company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, text="CapEx | 1,234", char_start=0, char_end=14, **kw)


def test_format_evidence_shows_unit_note():
    c = _chunk(unit_note="in EUR millions")
    assert "unit_note=in EUR millions" in format_evidence([c])
    assert "unit_note" not in format_evidence([c.model_copy(update={"unit_note": None})])


def test_table_chunk_carries_the_tables_unit_note():
    from arp.ingestion.parsing import chunk_document
    from arp.schemas.common import SourceDocument, TableSpan

    text = "Intro.\n\nCapEx | 1,234"
    doc = SourceDocument(
        company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="t", full_text=text,
        table_spans=[TableSpan(table_id="t1", char_start=text.index("CapEx"), char_end=len(text), unit_note="in EUR millions")],
    )
    (table_chunk,) = [c for c in chunk_document(doc) if "_table_" in c.chunk_id]
    assert "unit_note=in EUR millions" in format_evidence([table_chunk])


def _field(data_type):
    return FieldDefinition(name="f", description="d", data_type=data_type, extraction_instructions="look")


async def _prompt_for(fake_llm, data_type):
    llm = fake_llm({"ExtractionDraft": [ExtractionDraft(confidence=0.5)]})
    await extract_field("Acme", _field(data_type), [_chunk()], llm)
    return llm.prompts[0]


async def test_boolean_field_prompt_carries_three_outcome_rule(fake_llm):
    assert BOOLEAN_RULE in await _prompt_for(fake_llm, FieldDataType.BOOLEAN)


async def test_non_boolean_field_prompt_has_no_boolean_rule(fake_llm):
    assert BOOLEAN_RULE not in await _prompt_for(fake_llm, FieldDataType.CURRENCY_AMOUNT)


def test_uncited_false_is_not_grounded():
    # Guard: "false" with no quote is never accepted just because the verifier agrees.
    draft = ExtractionDraft(values=[PeriodValue(value=False, citations=[])], confidence=0.9)
    verifier = VerifierOutput(agrees=True, confidence=0.9, notes="ok")
    out = build_extracted_fields(_field(FieldDataType.BOOLEAN), draft, verifier, {}, fuzzy_threshold=0.9, confidence_review_threshold=0.6)
    assert ReasonCode.NOT_GROUNDED in out[0].review_reasons
