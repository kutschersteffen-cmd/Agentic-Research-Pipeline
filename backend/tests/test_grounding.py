from arp.grounding import ground_citations, is_grounded
from arp.schemas.common import Citation, DocType, SourceDocument


def test_exact_quote_is_grounded():
    source = "The company invested $500 million in green capex during fiscal 2025."
    assert is_grounded("invested $500 million in green capex", source)


def test_whitespace_variation_still_grounds():
    source = "Total  green   capex\nwas approximately $12 million."
    assert is_grounded("Total green capex was approximately $12 million.", source)


def test_hallucinated_quote_is_not_grounded():
    source = "The company discussed general R&D spending trends."
    assert not is_grounded("green capex reached $900 million", source)


def test_empty_quote_is_not_grounded():
    assert not is_grounded("", "some source text")


def test_ground_citations_marks_each_independently():
    doc = SourceDocument(
        company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="t",
        full_text="Green capex totaled $50 million in FY2025.",
    )
    good = Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Green capex totaled $50 million in FY2025.")
    bad = Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Green capex totaled $9 billion.")
    missing_doc = Citation(doc_id="doc_missing", doc_type=doc.doc_type, quote="anything")

    result = ground_citations([good, bad, missing_doc], {doc.doc_id: doc})
    assert result[0].grounded is True
    assert result[1].grounded is False
    assert result[2].grounded is False


def test_ground_citations_resolves_page_from_verified_match_position():
    page1 = "Page one talks about general strategy and has nothing about capex."
    page2 = "Green capex totaled $50 million in FY2025, per the EU Taxonomy KPI table."
    page3 = "Page three covers governance topics unrelated to capex."
    full_text = "\n\n".join([page1, page2, page3])
    page_breaks = [0, len(page1) + 2, len(page1) + 2 + len(page2) + 2]

    doc = SourceDocument(
        company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="t",
        full_text=full_text, page_breaks=page_breaks, local_path="/data/documents/c1/sustainability_report/report.pdf",
    )
    citation = Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Green capex totaled $50 million in FY2025")

    result = ground_citations([citation], {doc.doc_id: doc})[0]
    assert result.grounded is True
    assert result.page == 2
    assert result.company_id == "c1"
    assert result.source_filename == "report.pdf"


def test_ground_citations_resolves_sheet_from_verified_match_position():
    full_text = (
        "## Sheet: Overview\nCompany overview text goes here.\n\n"
        "## Sheet: EU Taxonomy\nCapex | 6912 | 92.6 | 1699 | 24.6\n\n"
        "## Sheet: Governance\nBoard composition details."
    )
    doc = SourceDocument(
        company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="t", full_text=full_text,
    )
    citation = Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Capex | 6912 | 92.6 | 1699 | 24.6")

    result = ground_citations([citation], {doc.doc_id: doc})[0]
    assert result.grounded is True
    assert result.sheet == "EU Taxonomy"
    assert result.page is None  # no page_breaks for an xlsx-derived document


def test_ungrounded_citation_gets_no_location_fields():
    doc = SourceDocument(
        company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="t",
        full_text="Nothing about the hallucinated figure here.", page_breaks=[0],
        local_path="/data/documents/c1/sustainability_report/report.pdf",
    )
    citation = Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Green capex reached $9 billion")

    result = ground_citations([citation], {doc.doc_id: doc})[0]
    assert result.grounded is False
    assert result.page is None
    assert result.sheet is None
    assert result.company_id is None
    assert result.source_filename is None


def test_grounded_citation_from_non_local_document_has_no_filename():
    """EDGAR-sourced documents have no local_path -- page/company_id still
    resolve, but source_filename stays None (no regression, no broken
    'view source' link for a source with nothing to link to)."""
    doc = SourceDocument(
        company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="t",
        full_text="Green capex totaled $50 million in FY2025.", source_url="https://sec.gov/filing.htm",
    )
    citation = Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Green capex totaled $50 million in FY2025.")

    result = ground_citations([citation], {doc.doc_id: doc})[0]
    assert result.grounded is True
    assert result.company_id == "c1"
    assert result.source_filename is None
    assert result.page is None
