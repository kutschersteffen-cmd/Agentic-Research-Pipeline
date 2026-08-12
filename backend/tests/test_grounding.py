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
