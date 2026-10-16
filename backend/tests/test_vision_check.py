import pytest
from reportlab.pdfgen import canvas

from arp.config import Settings
from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue
from arp.extraction.field_graph import extract_one_field
from arp.extraction.verifier_agent import VerifierOutput
from arp.extraction.vision_check import PageReading, check_on_page, cited_page, render_page, same_figure
from arp.ingestion.parsing import chunk_document
from arp.schemas.common import Citation, DocType, DocumentChunk, SourceDocument
from arp.schemas.datapoints import ExtractedField, FieldDataType, FieldDefinition
from arp.schemas.review import ReasonCode

_PAGE1 = "Acme Corp sustainability report. Introduction and strategy overview.\n"
_PAGE2 = "Environment table. Spills: 7 incidents in FY2024.\n"


@pytest.fixture
def pdf_doc(tmp_path) -> SourceDocument:
    path = tmp_path / "report.pdf"
    c = canvas.Canvas(str(path))
    for text in (_PAGE1, _PAGE2):
        c.drawString(72, 720, text.strip())
        c.showPage()
    c.save()
    return SourceDocument(
        company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG", full_text=_PAGE1 + _PAGE2,
        local_path=str(path), page_breaks=[0, len(_PAGE1)],
    )


def _field(high_risk=False) -> FieldDefinition:
    return FieldDefinition(
        name="spills", description="Number of spills", data_type=FieldDataType.NUMBER,
        extraction_instructions="spills", seed_keywords=["spills"], high_risk=high_risk,
    )


def _passage(doc: SourceDocument) -> DocumentChunk:
    start = len(_PAGE1)
    return DocumentChunk(
        chunk_id="p2", doc_id=doc.doc_id, company_id="c1", doc_type=doc.doc_type, text=_PAGE2,
        char_start=start, char_end=start + len(_PAGE2),
    )


def _ungrounded(doc: SourceDocument, raw="7") -> ExtractedField:
    return ExtractedField(
        field_id="spills", field_name="spills", value=7.0, raw_value_text=raw, confidence=0.9,
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Spills total seven", passage_id="p2")],
        review_reasons=[ReasonCode.NOT_GROUNDED], verifier_notes="Agreed.",
    )


def test_render_page_returns_png_and_none_out_of_range(pdf_doc):
    assert render_page(pdf_doc.local_path, 2)[:8] == b"\x89PNG\r\n\x1a\n"
    assert render_page(pdf_doc.local_path, 3) is None


def test_cited_page_maps_the_passage_to_its_pdf_page(pdf_doc):
    ef = _ungrounded(pdf_doc)
    assert cited_page(ef, {"p2": _passage(pdf_doc)}, {pdf_doc.doc_id: pdf_doc}) == (pdf_doc, 2)
    assert cited_page(ef, {}, {pdf_doc.doc_id: pdf_doc}) is None  # unknown passage
    html = pdf_doc.model_copy(update={"local_path": "report.html"})
    assert cited_page(ef, {"p2": _passage(pdf_doc)}, {pdf_doc.doc_id: html}) is None


def test_same_figure():
    assert same_figure("1,234.5", "1234.5")
    assert not same_figure("1,234.5", "1,243.5")
    assert not same_figure(None, "7")


async def _check(fake_llm, pdf_doc, reading, *, high_risk=False):
    llm = fake_llm({"PageReading": [reading]})
    ef, usage = await check_on_page(
        "Acme", _field(high_risk), _ungrounded(pdf_doc), {"p2": _passage(pdf_doc)}, {pdf_doc.doc_id: pdf_doc}, llm,
    )
    return ef, usage, llm


async def test_matching_page_clears_not_grounded(fake_llm, pdf_doc):
    ef, usage, llm = await _check(fake_llm, pdf_doc, PageReading(found=True, figure_text="7"))
    assert ef.review_reasons == []
    assert ef.verifier_notes.startswith("Agreed. Page 2 image shows '7', matching")
    assert usage is not None
    assert llm.images[0][0][:4] == b"\x89PNG"


async def test_high_risk_field_keeps_review_even_on_a_match(fake_llm, pdf_doc):
    ef, _, _ = await _check(fake_llm, pdf_doc, PageReading(found=True, figure_text="7"), high_risk=True)
    assert ef.review_reasons == [ReasonCode.NOT_GROUNDED]
    assert "matching the value" in ef.verifier_notes


@pytest.mark.parametrize("reading", [PageReading(found=True, figure_text="9"), PageReading(found=False)])
async def test_other_or_missing_figure_keeps_review(fake_llm, pdf_doc, reading):
    ef, _, _ = await _check(fake_llm, pdf_doc, reading)
    assert ef.review_reasons == [ReasonCode.NOT_GROUNDED]
    assert "not confirming the value" in ef.verifier_notes


async def test_no_pdf_page_makes_no_call(fake_llm, pdf_doc):
    llm = fake_llm({})
    ef = _ungrounded(pdf_doc)
    out, usage = await check_on_page("Acme", _field(), ef, {}, {pdf_doc.doc_id: pdf_doc}, llm)
    assert (out, usage, llm.calls) == (ef, None, [])


async def _extract(fake_llm, pdf_doc, *, enabled):
    [chunk] = [c for c in chunk_document(pdf_doc) if "Spills" in c.text]
    draft = ExtractionDraft(values=[PeriodValue(
        value=7, raw_value_text="7", period_text="FY2024",
        citations=[Citation(doc_id=pdf_doc.doc_id, doc_type=pdf_doc.doc_type, quote="Spills total seven", passage_id=chunk.chunk_id)],
    )], confidence=0.9)
    llm = fake_llm({
        "ExtractionDraft": [draft], "VerifierOutput": [VerifierOutput(agrees=True, confidence=0.9, notes="ok")],
        "PageReading": [PageReading(found=True, figure_text="7")],
    })
    rows, needs_review, usages = await extract_one_field(
        "Acme", _field(), documents=[pdf_doc], documents_by_id={pdf_doc.doc_id: pdf_doc}, llm=llm, verifier_llm=llm,
        settings=Settings(hybrid_retrieval_enabled=False, vision_fallback_enabled=enabled),
        fuzzy_threshold=0.92, confidence_review_threshold=0.6,
    )
    return rows, needs_review, usages, llm


async def test_field_graph_runs_the_check_only_when_enabled(fake_llm, pdf_doc):
    rows, needs_review, usages, llm = await _extract(fake_llm, pdf_doc, enabled=True)
    assert llm.calls == ["ExtractionDraft", "VerifierOutput", "PageReading"]
    assert (rows[0].review_reasons, needs_review, len(usages)) == ([], False, 3)

    rows, needs_review, _, llm = await _extract(fake_llm, pdf_doc, enabled=False)
    assert "PageReading" not in llm.calls
    assert (rows[0].review_reasons, needs_review) == ([ReasonCode.NOT_GROUNDED], True)
