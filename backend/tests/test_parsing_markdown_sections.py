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


def test_text_without_markdown_headings_and_transcripts_are_unchanged():
    plain = "ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS\n\n" + "Revenue grew in every segment. " * 20
    assert {c.section for c in chunk_document(_doc(plain, DocType.ANNUAL_REPORT_10K), chunk_chars=200, overlap_chars=0)
            if c.char_start > 100} == {None}
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
