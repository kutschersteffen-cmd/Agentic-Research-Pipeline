"""Argus runs: a kept document with no text fails its company, marked as a document problem; other runs are unchanged."""

import asyncio
import re

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


def test_image_placeholders_are_not_text():
    """Docling writes '<!-- image -->' for a picture: an image-only page has no text the run could read."""
    registry = KeptDocuments(_Registry([_doc("a", "<!-- image -->\n\n<!-- image -->")]), {"aapl": {"a"}})
    with pytest.raises(UnreadableDocument, match=r"^No text could be read from a\.pdf$"):
        asyncio.run(registry.fetch_all(APPLE))


def test_a_kept_file_the_fetch_could_not_parse_fails_the_company():
    """A file that failed to parse is left out of the fetch (logged, never raised): that is a kept file with no text too."""
    registry = KeptDocuments(_Registry([_doc("b", "Apple annual report")]), {"aapl": {"a", "b"}}, names={"a": "scan.pdf"})
    with pytest.raises(UnreadableDocument, match=r"^No text could be read from scan\.pdf$"):
        asyncio.run(registry.fetch_all(APPLE))
    narrowed = asyncio.run(registry.fetch_all(APPLE, [DocType.ANNUAL_REPORT_10K]))  # a doc-type fetch may leave kept files out
    assert [d.content_key for d in narrowed] == ["b"]


def test_blank_and_image_only_pdfs_through_the_real_document_source(tmp_path, pg):
    """The live path: the real local source with the real content store, as the API builds it (arp.api.deps.build_registry)."""
    from PIL import Image, ImageDraw
    from pypdf import PdfWriter

    from arp.config import Settings
    from arp.ingestion.local_files import LocalFileDocumentSource
    from arp.ingestion.registry import DocumentSourceRegistry
    from arp.retrieval.content_store_factory import content_store_for

    settings = Settings(anthropic_api_key="unused", postgres_dsn=pg, documents_dir=tmp_path / "docs",
                        document_store_dir=tmp_path / "store", cache_dir=tmp_path / "cache")
    folder = settings.documents_dir / "aapl" / "10-K"
    folder.mkdir(parents=True)
    w = PdfWriter()
    w.add_blank_page(612, 792)
    w.write(folder / "blank.pdf")
    img = Image.new("RGB", (800, 1000), "white")
    ImageDraw.Draw(img).rectangle((100, 100, 700, 300), fill="black")  # a picture, no words
    img.save(folder / "scan.pdf", "PDF")
    store = content_store_for(settings)
    source = DocumentSourceRegistry([LocalFileDocumentSource(settings.documents_dir, content_store=store)])
    for name in ("blank.pdf", "scan.pdf"):
        key = store.content_key_for_file(folder / name)
        kept = KeptDocuments(source, {"aapl": {key}}, names={key: name})
        with pytest.raises(UnreadableDocument, match="^No text could be read from " + re.escape(name) + "$"):  # AC-37
            asyncio.run(kept.fetch_all(APPLE))


class _Source:
    def __init__(self, name, docs=None, error=None):
        self.name, self.docs, self.error = name, docs or [], error

    async def fetch(self, company, doc_types=None):
        if self.error:
            raise self.error
        return list(self.docs)


def _same_text(key, name):
    d = _doc(key, "Apple annual report 2025", path=f"/docs/aapl/10-K/{name}")
    d.sha256 = "same-text"  # the registry dedups on the text's hash; the kept list holds the files' byte hashes
    return d


@pytest.mark.parametrize("order", [("kept", "other"), ("other", "kept")])
def test_a_kept_file_with_the_same_text_as_another_is_not_lost_to_the_dedup(order):
    from arp.ingestion.registry import DocumentSourceRegistry

    docs = {"kept": _same_text("k", "report.pdf"), "other": _same_text("o", "report-resaved.pdf")}
    registry = KeptDocuments(DocumentSourceRegistry([_Source("local", [docs[x] for x in order])]), {"aapl": {"k"}})
    assert [d.content_key for d in asyncio.run(registry.fetch_all(APPLE))] == ["k"]


def test_a_source_that_failed_as_a_whole_is_not_a_file_without_text():
    from arp.ingestion.registry import DocumentSourceRegistry, KeptFileMissing

    inner = DocumentSourceRegistry([_Source("local", error=OSError("disk gone")), _Source("edgar", [_doc("b", "text")])])
    with pytest.raises(KeptFileMissing, match=r"^Kept file not found: a\.pdf$") as err:
        asyncio.run(KeptDocuments(inner, {"aapl": {"a", "b"}}, names={"a": "a.pdf"}).fetch_all(APPLE))
    assert not getattr(err.value, "document_problem", False)  # nothing to replace: no Replace file
