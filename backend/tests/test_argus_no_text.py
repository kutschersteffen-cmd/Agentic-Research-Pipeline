"""Argus runs: a kept document with no text fails its company, marked as a document problem; other runs are unchanged."""

import asyncio

import pytest

from arp.ingestion.registry import KeptDocuments, UnreadableDocument
from arp.orchestration.batch_runner import BatchSinks, run_batch
from arp.schemas.common import CompanyRef, DocType, SourceDocument


class _Registry:
    def __init__(self, docs):
        self.docs = docs

    async def fetch_all(self, company, doc_types=None):
        return list(self.docs)


def _doc(key, text, path="/docs/aapl/10-K/a.pdf"):
    return SourceDocument(company_id="aapl", doc_type=DocType.ANNUAL_REPORT_10K, title="A report", full_text=text,
                          content_key=key, local_path=path)


APPLE = CompanyRef(company_id="aapl", name="Apple")


def test_a_kept_document_without_text_fails_the_company():
    registry = KeptDocuments(_Registry([_doc("a", "   \n"), _doc("b", "Apple annual report")]), {"aapl": {"a", "b"}})
    with pytest.raises(UnreadableDocument, match=r"^No text could be read from a\.pdf$"):
        asyncio.run(registry.fetch_all(APPLE))


def test_a_removed_document_without_text_and_other_runs_are_unchanged():
    docs = [_doc("a", ""), _doc("b", "Apple annual report")]
    assert len(asyncio.run(KeptDocuments(_Registry(docs), {"aapl": {"b"}}).fetch_all(APPLE))) == 1  # the empty one was removed
    assert len(asyncio.run(KeptDocuments(_Registry(docs), {}).fetch_all(APPLE))) == 2  # no kept list for Apple: as before


def test_the_error_row_says_it_is_a_document_problem():
    rows: list[dict] = []

    async def worker(company):
        raise UnreadableDocument("No text could be read from a.pdf")

    sinks = BatchSinks(done=set, append_result=rows.append, append_error=rows.append)
    asyncio.run(run_batch([APPLE], item_key=lambda c: c.company_id, worker=worker, sinks=sinks, concurrency=1,
                          result_to_json=dict))
    assert rows[0]["error"] == "No text could be read from a.pdf" and rows[0]["document_problem"] is True


def test_other_failures_are_not_document_problems():
    rows: list[dict] = []

    async def worker(company):
        raise RuntimeError("model down")

    sinks = BatchSinks(done=set, append_result=rows.append, append_error=rows.append)
    asyncio.run(run_batch([APPLE], item_key=lambda c: c.company_id, worker=worker, sinks=sinks, concurrency=1,
                          result_to_json=dict))
    assert "document_problem" not in rows[0]
