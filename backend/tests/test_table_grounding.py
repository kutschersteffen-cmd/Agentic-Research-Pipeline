import os
from types import SimpleNamespace

import pytest

from arp.checks.numeric import check_caption_scale, check_row_label
from arp.checks.runner import CheckContext
from arp.extraction.aggregator import build_extracted_fields
from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue
from arp.extraction.verifier_agent import VerifierOutput
from arp.grounding import ground_citations
from arp.ingestion import local_files
from arp.ingestion.local_files import parse_file_to_text_with_pages, table_spans_from_docling
from arp.ingestion.parsing import chunk_document
from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument
from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition
from arp.schemas.review import ReasonCode

# Docling's own markdown for this table (TableItem.export_to_markdown(doc), tabulate "github" format).
MD = (
    "|         |   FY2024 |   FY2023 |\n"
    "|---------|----------|----------|\n"
    "| Revenue |  1,234.5 |  1,100.0 |\n"
    "| EBIT    |      200 |      150 |"
)
CAPTION = "Table 3: Revenue by segment (in EUR million)"
TEXT = f"Annual report 2024.\n\n{CAPTION}\n\n{MD}\n\nRevenue grew strongly in FY2024 across all segments."


class _FakeTable:
    """The attributes table_spans_from_docling reads from a real docling TableItem:
    `export_to_markdown(doc)`, `caption_text(doc)` ("" when the table has no caption item),
    and `data.table_cells`, each with `text`, `start_row_offset_idx`, `start_col_offset_idx`,
    `row_header` and `column_header`."""

    def __init__(self, rows, md, caption=""):
        self._md, self._caption = md, caption
        self.data = SimpleNamespace(table_cells=[
            SimpleNamespace(text=t, start_row_offset_idx=r, start_col_offset_idx=c,
                            column_header=r == 0, row_header=c == 0 and r > 0)
            for r, row in enumerate(rows) for c, t in enumerate(row)
        ])

    def export_to_markdown(self, doc=None):
        return self._md

    def caption_text(self, doc):
        return self._caption


_ROWS = [["", "FY2024", "FY2023"], ["Revenue", "1,234.5", "1,100.0"], ["EBIT", "200", "150"]]


def _doc(text=TEXT, rows=_ROWS, md=MD, decimal=None):
    fake = SimpleNamespace(tables=[_FakeTable(rows, md)])
    return SourceDocument(doc_id="d1", company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="t", full_text=text,
                          table_spans=table_spans_from_docling(fake, text), decimal=decimal)


def _ground(doc, quote):
    (c,) = ground_citations([Citation(doc_id="d1", doc_type=doc.doc_type, quote=quote)], {"d1": doc})
    return c


def test_value_in_table_cell_cites_the_cell():
    c = _ground(_doc(), "Revenue |  1,234.5")
    assert c.grounded
    ref = c.table_ref
    assert (ref.row_label, ref.col_label) == ("Revenue", "FY2024")
    assert ref.caption == CAPTION
    assert ref.unit_note == "in EUR million"


def test_value_outside_table_has_no_table_ref():
    c = _ground(_doc(), "Revenue grew strongly in FY2024 across all segments")
    assert c.grounded and c.table_ref is None


def test_unlocatable_table_is_skipped():
    fake = SimpleNamespace(tables=[_FakeTable(_ROWS, MD.replace("1,234.5", "9,999.9"))])
    assert table_spans_from_docling(fake, TEXT) == []


def test_chunk_document_emits_table_chunk():
    chunks = chunk_document(_doc())
    (table_chunk,) = [c for c in chunks if c.section == CAPTION]
    assert table_chunk.text == MD


def test_old_citation_without_table_ref_still_loads():
    c = Citation.model_validate({"doc_id": "d1", "doc_type": "sustainability_report", "quote": "q", "table_ref": None})
    assert c.table_ref is None
    for legacy in ("Table 3", 3):  # old rows / model drafts wrote free text here
        c = Citation.model_validate({"doc_id": "d1", "doc_type": "sustainability_report", "quote": "q", "table_ref": legacy})
        assert c.table_ref is None
    draft = ExtractionDraft.model_validate_json(
        '{"values": [{"value": 1, "citations": [{"doc_id": "d1", "doc_type": "sustainability_report",'
        ' "quote": "q", "table_ref": "Table 3"}]}], "confidence": 0.9}'
    )
    assert draft.values[0].citations[0].table_ref is None
    assert SourceDocument.model_validate(
        {"company_id": "c", "doc_type": "sustainability_report", "title": "t", "full_text": "x"}
    ).table_spans == []


def test_pdf_parse_returns_table_spans(monkeypatch, tmp_path):
    doc = SimpleNamespace(pages={1: object()}, tables=[_FakeTable(_ROWS, MD)],
                          export_to_markdown=lambda page_no: TEXT)
    converter = SimpleNamespace(convert=lambda path: SimpleNamespace(document=doc))
    monkeypatch.setattr(local_files, "_docling_converter", lambda ocr=True: converter)
    path = tmp_path / "r.pdf"
    path.write_bytes(b"%PDF fake")
    text, _breaks, spans = parse_file_to_text_with_pages(path)
    (span,) = spans
    assert text[span.char_start : span.char_end] == MD


def _spec(name, **kw):
    return FieldDefinition(field_id="f1", name=name, description="d", data_type=FieldDataType.NUMBER,
                           extraction_instructions="i", **kw)


def _check(check, spec, citation, scale=None):
    from arp.schemas.datapoints import ExtractedField

    field = ExtractedField(field_id="f1", field_name="f1", value=1234.5, raw_value_text="1,234.5", confidence=0.9,
                           value_state="found", citations=[citation], scale_applied=scale)
    ctx = CheckContext(company=CompanyRef(company_id="c1", name="A"), issuer_key="k",
                       schema=DataPointSchema(name="s", fields=[spec]), documents_by_id={"d1": _doc()},
                       record_fields=[field])
    (r,) = check(spec, field, ctx)
    return r


def test_checks_read_the_table_ref():
    c = _ground(_doc(), "Revenue |  1,234.5")
    assert _check(check_caption_scale, _spec("Revenue"), c).outcome == "fail"  # caption says million
    assert _check(check_caption_scale, _spec("Revenue"), c, scale=1e6).outcome == "pass"
    assert _check(check_row_label, _spec("Revenue"), c).outcome == "pass"
    assert _check(check_row_label, _spec("Scope 1 emissions"), c).outcome == "fail"


def test_table_decimal_overrides_document_decimal():
    rows = [["", "FY2024", "FY2023"], ["Revenue", "1,234", "1,100.5"], ["EBIT", "2,000.5", "150.25"]]
    md = (
        "|         |   FY2024 |   FY2023 |\n"
        "|---------|----------|----------|\n"
        "| Revenue |    1,234 |  1,100.5 |\n"
        "| EBIT    |  2,000.5 |   150.25 |"
    )
    text = f"{CAPTION}\n\n{md}\n"
    doc = _doc(text=text, rows=rows, md=md, decimal="comma")
    cit = Citation(doc_id="d1", doc_type=doc.doc_type, quote="Revenue |    1,234")
    draft = ExtractionDraft(values=[PeriodValue(value="1,234", raw_value_text="1,234", citations=[cit])],
                            confidence=0.9)
    (f,) = build_extracted_fields(_spec("Revenue"), draft, VerifierOutput(agrees=True, confidence=0.9, notes=""),
                                  {"d1": doc}, fuzzy_threshold=0.9, confidence_review_threshold=0.6)
    assert f.value == 1234.0
    assert ReasonCode.NUMBER_LOCALE_AMBIGUOUS not in f.review_reasons


def test_table_spans_survive_the_parse_cache(tmp_path):
    import sqlite3

    from arp.storage.document_store import DocumentContentStore

    db = tmp_path / "content.db"  # a database from before the table_spans column
    sqlite3.connect(db).executescript(
        "CREATE TABLE parsed_content (id INTEGER PRIMARY KEY, content_key TEXT NOT NULL, key_kind TEXT NOT NULL,"
        " parser_version TEXT NOT NULL, source_suffix TEXT NOT NULL, full_text TEXT NOT NULL,"
        " page_breaks TEXT NOT NULL DEFAULT '[]', text_sha256 TEXT NOT NULL, char_len INTEGER NOT NULL,"
        " byte_size INTEGER NOT NULL, created_at TEXT NOT NULL);"
    )
    spans = _doc().table_spans
    kw = {"key_kind": "file_bytes", "parser_version": "p", "source_suffix": ".pdf", "byte_size": 1}
    DocumentContentStore(tmp_path).get_or_compute("k", compute=lambda: (TEXT, [], spans), **kw)
    hit = DocumentContentStore(tmp_path).get_or_compute("k", compute=lambda: 1 / 0, **kw)
    assert SourceDocument(company_id="c", doc_type=DocType.SUSTAINABILITY_REPORT, title="t", full_text=TEXT,
                          table_spans=hit.table_spans).table_spans == spans


@pytest.mark.skipif(not os.environ.get("ARP_TEST_DOCLING_MODELS"),
                    reason="ARP_TEST_DOCLING_MODELS not set -- needs Docling's layout/table models (Hugging Face Hub)")
def test_real_pdf_table_is_located_in_the_page_markdown(tmp_path):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

    path = tmp_path / "t.pdf"
    grid = Table(_ROWS)
    grid.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, "black")]))
    SimpleDocTemplate(str(path), pagesize=A4).build([Paragraph(CAPTION, getSampleStyleSheet()["Normal"]), grid])

    text, _breaks, (span,) = parse_file_to_text_with_pages(path)  # real converter: page markdown holds the table's
    cells = {(c.row_label, c.col_label): text[c.char_start : c.char_end] for c in span.cells}
    assert cells[("Revenue", "FY2024")] == "1,234.5" and cells[("EBIT", "FY2023")] == "150"
    assert (span.caption, span.unit_note) == (CAPTION, "in EUR million")
