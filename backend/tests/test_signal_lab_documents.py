from arp.schemas.common import DocType, SourceDocument
from arp.signal_lab.documents import records_from_documents

KT = "2024-01-01T00:00:00Z"


def _doc(doc_type=DocType.ANNUAL_REPORT_10K, published_at="2023-02-03T16:05:23.000Z"):
    return SourceDocument(
        doc_id="d1",
        company_id="AAPL",
        doc_type=doc_type,
        title="T",
        full_text="body",
        source_url="http://x",
        published_at=published_at,
    )


def test_edgar_doc_maps_to_record():
    [rec] = records_from_documents([_doc()], knowledge_time=KT)
    assert rec.source == "edgar"
    assert rec.source_item_id == "d1"
    assert rec.company_id == "AAPL"
    assert rec.event_time == "2023-02-03T16:05:23Z"
    assert rec.body == "body"
    assert rec.source_url == "http://x"


def test_date_only_is_end_of_day():
    [rec] = records_from_documents([_doc(published_at="2023-02-03")], knowledge_time=KT)
    assert rec.event_time == "2023-02-03T23:59:59Z"


def test_doc_without_published_at_is_skipped():
    assert records_from_documents([_doc(published_at=None)], knowledge_time=KT) == []


def test_transcript_and_other_sources():
    [t] = records_from_documents([_doc(DocType.EARNINGS_TRANSCRIPT)], knowledge_time=KT)
    [o] = records_from_documents([_doc(DocType.OTHER)], knowledge_time=KT)
    assert (t.source, o.source) == ("transcript", "document")
