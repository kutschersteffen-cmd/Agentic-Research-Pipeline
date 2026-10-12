from arp.extraction.extractor_agent import format_evidence
from arp.schemas.common import DocType, DocumentChunk


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
