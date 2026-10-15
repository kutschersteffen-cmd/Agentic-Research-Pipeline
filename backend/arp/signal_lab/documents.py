from __future__ import annotations

from arp.schemas.common import DocType, SourceDocument
from arp.signal_lab.text_store import TextRecord, make_record

_SOURCES = {
    DocType.ANNUAL_REPORT_10K: "edgar",
    DocType.PROXY_DEF14A: "edgar",
    DocType.EARNINGS_TRANSCRIPT: "transcript",
}


def records_from_documents(docs: list[SourceDocument], *, knowledge_time: str) -> list[TextRecord]:
    # No published_at means no event time, so no evidence: skip.
    return [
        make_record(
            source=_SOURCES.get(doc.doc_type, "document"),
            source_item_id=doc.doc_id,
            company_id=doc.company_id,
            event_time=doc.published_at,
            knowledge_time=knowledge_time,
            title=doc.title,
            body=doc.full_text,
            source_url=doc.source_url,
        )
        for doc in docs
        if doc.published_at
    ]
