from arp.ingestion.parsing import chunk_document
from arp.planning.doc_routing import section_filter
from arp.schemas.common import DocType, SourceDocument
from arp.schemas.datapoints import DocumentRouting, FieldDataType, FieldDefinition

_MD = (
    "# Annual Report 2024\n\nOverview of the year.\n\n"
    "## Remuneration report\n\n" + "The annual bonus carries a 40% ESG weight. " * 60 + "\n\n"
    "## Climate strategy ##\n\n" + "We target net zero by 2045 across scopes 1 and 2. " * 60
)


def _doc(text: str, doc_type=DocType.SUSTAINABILITY_REPORT) -> SourceDocument:
    return SourceDocument(company_id="c1", doc_type=doc_type, title="AR", full_text=text)


def test_docling_markdown_headings_become_chunk_sections():
    chunks = chunk_document(_doc(_MD), chunk_chars=1200, overlap_chars=100)
    by_start = {c.char_start: c.section for c in chunks}
    assert by_start[0] == "Annual Report 2024"
    assert {c.section for c in chunks} == {"Annual Report 2024", "Remuneration report", "Climate strategy"}
    climate = _MD.index("## Climate strategy")
    assert all(c.section == "Climate strategy" for c in chunks if c.char_start > climate)  # trailing #'s dropped


def test_10k_item_headers_carry_to_every_chunk_until_the_next_one_and_transcripts_get_none():
    tenk = (
        "Cover page.\n\nITEM 1. BUSINESS\n\n" + "We make widgets. " * 150
        + "\n\nItem 7. Management's Discussion and Analysis\n\n" + "Revenue grew. " * 150
        + "\n\nItem 7 of the credit agreement, as amended, requires the borrower to keep a leverage ratio below 3x."
    )
    chunks = chunk_document(_doc(tenk, DocType.ANNUAL_REPORT_10K), chunk_chars=900, overlap_chars=50)
    item7 = tenk.index("Item 7.")
    assert chunks[0].section is None  # nothing before the first header
    assert {c.section for c in chunks if 0 < c.char_start < item7} == {"ITEM 1. BUSINESS"}
    # every later chunk, even far from the header; a long body line starting "Item 7" is not a header
    assert {c.section for c in chunks if c.char_start > item7} == {"Item 7. Management's Discussion and Analysis"}
    [chunk] = chunk_document(_doc("## Q3 call\n\nOperator: welcome.", DocType.EARNINGS_TRANSCRIPT))
    assert chunk.section is None


def test_section_routing_now_narrows_a_pdf_report():
    field = FieldDefinition(
        name="bonus", description="d", data_type=FieldDataType.STRING, extraction_instructions="x",
        document_routing=DocumentRouting(sections=["remuneration report"]),
    )
    chunks = chunk_document(_doc(_MD), chunk_chars=1200, overlap_chars=100)
    kept = section_filter(field, chunks)
    assert kept and len(kept) < len(chunks)
    assert {c.section for c in kept} == {"Remuneration report"}
