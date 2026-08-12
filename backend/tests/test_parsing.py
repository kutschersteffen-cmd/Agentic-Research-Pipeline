from arp.ingestion.parsing import chunk_document, find_keyword_hits
from arp.schemas.common import DocType, SourceDocument


def test_chunking_covers_whole_document_without_gaps():
    text = ("Paragraph one about green capex.\n\n" * 50) + "Final paragraph."
    doc = SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="t", full_text=text)
    chunks = chunk_document(doc, chunk_chars=500, overlap_chars=50)

    assert len(chunks) > 1
    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == len(text)
    # every char position should be covered by at least one chunk
    covered = [False] * len(text)
    for c in chunks:
        for i in range(c.char_start, c.char_end):
            covered[i] = True
    assert all(covered)


def test_keyword_hits_detected_case_insensitively():
    text = "The company expanded its Green Capex program significantly."
    doc = SourceDocument(company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="t", full_text=text)
    chunks = chunk_document(doc, keywords=["green capex", "biodiversity"])
    assert "green capex" in chunks[0].keyword_hits
    assert "biodiversity" not in chunks[0].keyword_hits


def test_find_keyword_hits_helper():
    assert find_keyword_hits("Solar and wind power expansion", ["solar", "nuclear"]) == ["solar"]


def test_empty_document_produces_no_chunks():
    doc = SourceDocument(company_id="c1", doc_type=DocType.OTHER, title="t", full_text="")
    assert chunk_document(doc) == []
