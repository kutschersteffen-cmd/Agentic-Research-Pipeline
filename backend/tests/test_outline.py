from arp.ingestion.outline import outline
from arp.ingestion.parsing import chunk_document
from arp.schemas.common import DocType, SourceDocument, TableSpan

_PAGES = [
    "Cover.\n\n",
    "Introduction text.\n\n",
    "## E1 Climate change\n\nOur climate approach.\n\n",
    "## Targets\n\nWe target net zero by 2045.\n\n",
    "More text.\n\n",
    "Even more.\n\n",
    "## EU Taxonomy\n\nAligned capex was EUR 1.2bn.",
]


def _doc() -> SourceDocument:
    breaks, cursor = [], 0
    for p in _PAGES:
        breaks.append(cursor)
        cursor += len(p)
    return SourceDocument(doc_id="d1", company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="t",
                          full_text="".join(_PAGES), page_breaks=breaks)


def test_ac7_outline_titles_pages_and_ranges():
    doc = _doc()
    entries = outline(doc)
    assert [(e.title, e.page) for e in entries] == [("E1 Climate change", 3), ("Targets", 4), ("EU Taxonomy", 7)]
    assert [e.char_end for e in entries[:-1]] == [e.char_start for e in entries[1:]]
    assert entries[-1].char_end == len(doc.full_text)


def test_ac8_targets_tagged_climate_targets():
    assert "climate_targets" in outline(_doc())[1].tags


def test_ac8b_eu_taxonomy_tagged():
    assert "eu_taxonomy" in outline(_doc())[2].tags


def test_ac8c_outline_is_stable():
    doc = _doc()
    assert outline(doc) == outline(doc)


def test_ac9_ac9b_chunk_under_eu_taxonomy_gets_its_tags_and_page():
    doc = _doc()
    at = doc.full_text.index("## EU Taxonomy")
    chunks = chunk_document(doc, chunk_chars=60, overlap_chars=0)
    chunk = next(c for c in chunks if c.char_start >= at and c.table_id is None)
    assert "eu_taxonomy" in chunk.section_tags
    assert chunk.page == 7


_TABLE = "| | 2025 |\n|---|---|\n| ## Wind | 1 |"
_TEXT = f"## E1\n\nIntro.\n\n## EU Taxonomy\n\nCapEx KPI\n\n{_TABLE}\n\nAfter."


def _table_doc() -> SourceDocument:
    start = _TEXT.index(_TABLE)
    span = TableSpan(table_id="table_0", char_start=start, char_end=start + len(_TABLE), caption="CapEx KPI",
                     heading_path=["E1", "EU Taxonomy"], page=1)
    return SourceDocument(doc_id="d2", company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="t",
                          full_text=_TEXT, table_spans=[span])


def _table_chunk():
    return next(c for c in chunk_document(_table_doc()) if c.table_id is not None)


def test_ac9c_table_chunk_section_is_its_heading():
    assert _table_chunk().section == "EU Taxonomy"


def test_ac9d_table_chunk_caption():
    assert _table_chunk().caption == "CapEx KPI"


def test_ac9e_table_chunk_table_id():
    assert _table_chunk().table_id == "table_0"


def test_heading_inside_a_table_span_starts_no_outline_entry():
    # a cell starting a line with "## " (a hand-built span) must not open an entry inside the table
    text = "## EU Taxonomy\n\n| a |\n|---|\n\n## Wind\n\n| 1 |\n\n## Targets\n\nText."
    start, end = text.index("| a |"), text.index("| 1 |") + len("| 1 |")
    doc = SourceDocument(doc_id="d3", company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="t", full_text=text,
                         table_spans=[TableSpan(table_id="table_0", char_start=start, char_end=end)])
    assert [e.title for e in outline(doc)] == ["EU Taxonomy", "Targets"]


def test_document_without_headings_has_an_empty_outline():
    doc = SourceDocument(doc_id="d4", company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="t", full_text="Plain text.")
    assert outline(doc) == []
