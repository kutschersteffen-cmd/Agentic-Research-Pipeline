from pathlib import Path
from types import SimpleNamespace

import pytest

from arp.grounding import ground_citations
from arp.ingestion.local_files import _extract_pdf_text_local, table_spans_from_docling
from arp.ingestion.table_kinds import table_kind
from arp.schemas.common import Citation, DocType, SourceDocument

FIXTURE = Path(__file__).parent / "fixtures" / "tables" / "capex_two_header_rows.pdf"


@pytest.fixture(scope="module")
def parsed():
    """The real Docling parse of a 2-page PDF: page 2 holds heading "EU Taxonomy – CapEx KPI" and a
    table whose header rows are "in € million" | "Proportion of CapEx" (spanning) over "" | "2025" | "2024"."""
    text, page_breaks, spans = _extract_pdf_text_local(FIXTURE)
    (span,) = spans
    return text, span


def test_ac1_column_headers_join_every_header_row(parsed):
    _, span = parsed
    assert span.column_headers == ["", "Proportion of CapEx – 2025", "Proportion of CapEx – 2024"]


def test_ac1b_cell_col_label_is_the_full_header_path(parsed):
    text, span = parsed
    cell = next(c for c in span.cells if c.row_label == "Wind" and text[c.char_start : c.char_end] == "1,234")
    assert cell.col_label == "Proportion of CapEx – 2025"


def test_ac1c_row_labels(parsed):
    assert parsed[1].row_labels == ["Wind", "Solar"]


def test_ac2_page(parsed):
    assert parsed[1].page == 2


def test_ac2b_heading_path(parsed):
    # Docling's PDF text layer turns the drawn en dash into a hyphen
    assert parsed[1].heading_path[-1] == "EU Taxonomy - CapEx KPI"


def test_ac3_scale_from_a_header_cell(parsed):
    assert parsed[1].scale == "million"


def test_ac3b_unit_from_a_header_cell(parsed):
    assert parsed[1].unit == "€"


def test_ac4_kind(parsed):
    assert parsed[1].kind == "eu_taxonomy_capex"


class _FakeTable:
    def __init__(self, rows, md, caption="", pages=()):
        self._md, self._caption = md, caption
        self.prov = [SimpleNamespace(page_no=p) for p in pages]
        self.data = SimpleNamespace(table_cells=[
            SimpleNamespace(text=t, start_row_offset_idx=r, start_col_offset_idx=c,
                            column_header=r == 0, row_header=c == 0 and r > 0)
            for r, row in enumerate(rows) for c, t in enumerate(row)
        ])

    def export_to_markdown(self, doc=None):
        return self._md

    def caption_text(self, doc):
        return self._caption


def _md(rows):
    lines = ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join([lines[0], "|" + "---|" * len(rows[0]), *lines[1:]])


def _span(rows, caption="", text_before="", pages=()):
    md = _md(rows)
    text = f"{text_before}{md}\n\nAfter."
    (span,) = table_spans_from_docling(SimpleNamespace(tables=[_FakeTable(rows, md, caption, pages)]), text)
    return span


def test_ac3c_caption_scale_wins_over_header_cell():
    span = _span([["in € million", "2025"], ["Wind", "1"]], caption="CapEx in EUR thousand")
    assert span.scale == "thousand"


def test_ac3d_unit_from_a_unit_column():
    span = _span([["", "Unit", "2025"], ["Scope 1", "t CO2e", "100"]])
    assert span.unit == "t CO2e"
    assert span.scale is None


def test_ac5_opex_kind():
    assert table_kind("Taxonomy-aligned OpEx", ["EU Taxonomy"], []) == "eu_taxonomy_opex"


def test_ac6_no_matching_words():
    assert table_kind("Headcount by region", ["Workforce"], ["2025"]) is None


def test_table_on_two_pages_takes_the_first_page_and_its_heading():
    span = _span([["", "2025"], ["Wind", "1"]], text_before="## EU Taxonomy\n\nIntro.\n\n", pages=(3, 4))
    assert span.page == 3
    assert span.heading_path == ["EU Taxonomy"]


def test_empty_table_gets_metadata_and_kind_from_caption():
    span = _span([["", ""]], caption="Taxonomy-eligible CapEx")
    assert span.cells == [] and span.row_labels == []
    assert span.kind == "eu_taxonomy_capex"


def test_ac23_citation_table_ref_carries_page_and_kind():
    rows = [["", "2025"], ["Wind", "1,234"]]
    md = _md(rows)
    text = f"## EU Taxonomy\n\nCapEx KPI\n\n{md}\n\nAfter."
    spans = table_spans_from_docling(SimpleNamespace(tables=[_FakeTable(rows, md, "CapEx KPI", pages=(7,))]), text)
    doc = SourceDocument(doc_id="d1", company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="t",
                         full_text=text, table_spans=spans)
    (c,) = ground_citations([Citation(doc_id="d1", doc_type=doc.doc_type, quote="Wind | 1,234")], {"d1": doc})
    assert c.grounded
    assert (c.table_ref.page, c.table_ref.kind) == (7, "eu_taxonomy_capex")
