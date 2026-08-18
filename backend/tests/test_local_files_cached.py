import asyncio

from arp.grounding import ground_citations
from arp.ingestion import local_files
from arp.ingestion.local_files import LocalFileDocumentSource
from arp.schemas.common import Citation, CompanyRef, DocType
from arp.storage.document_store import DocumentContentStore


class _FakeDoclingDocument:
    """See test_local_files_pdf_pages.py's copy for why this fakes Docling
    instead of driving its real (network-dependent) ML pipeline."""

    def __init__(self, page_texts: list[str]):
        self._page_texts = page_texts
        self.pages = {i + 1: object() for i in range(len(page_texts))}

    def export_to_markdown(self, page_no: int) -> str:
        return self._page_texts[page_no - 1]


class _FakeConversionResult:
    def __init__(self, document: _FakeDoclingDocument):
        self.document = document


class _FakeDoclingConverter:
    def __init__(self, page_texts: list[str]):
        self._page_texts = page_texts

    def convert(self, path):
        return _FakeConversionResult(_FakeDoclingDocument(self._page_texts))


def _write_doc(tmp_path, company_id, doc_type, name, text):
    d = tmp_path / "docs" / company_id / doc_type.value
    d.mkdir(parents=True, exist_ok=True)
    path = d / name
    path.write_text(text)
    return path


def test_fetch_without_a_store_behaves_exactly_as_before(tmp_path):
    _write_doc(tmp_path, "acme", DocType.ANNUAL_REPORT_10K, "report.txt", "Some disclosure text about green capex.")
    source = LocalFileDocumentSource(tmp_path / "docs")

    docs = asyncio.run(source.fetch(CompanyRef(company_id="acme", name="Acme")))

    assert len(docs) == 1
    assert docs[0].full_text == "Some disclosure text about green capex."
    assert docs[0].doc_id.startswith("doc_")
    # two fetches with no store produce two different random ids, exactly
    # like the pre-existing behavior.
    docs_again = asyncio.run(source.fetch(CompanyRef(company_id="acme", name="Acme")))
    assert docs_again[0].doc_id != docs[0].doc_id


def test_doc_id_is_stable_across_two_fetches(tmp_path):
    _write_doc(tmp_path, "acme", DocType.ANNUAL_REPORT_10K, "report.txt", "Some disclosure text about green capex.")
    store = DocumentContentStore(tmp_path / "store")
    source = LocalFileDocumentSource(tmp_path / "docs", content_store=store)

    first = asyncio.run(source.fetch(CompanyRef(company_id="acme", name="Acme")))
    second = asyncio.run(source.fetch(CompanyRef(company_id="acme", name="Acme")))

    assert first[0].doc_id == second[0].doc_id
    assert first[0].doc_id.startswith("doc_")


def test_doc_id_differs_per_company_for_identical_bytes(tmp_path):
    _write_doc(tmp_path, "acme", DocType.ANNUAL_REPORT_10K, "report.txt", "Identical content across companies.")
    _write_doc(tmp_path, "beta", DocType.ANNUAL_REPORT_10K, "report.txt", "Identical content across companies.")
    store = DocumentContentStore(tmp_path / "store")
    source = LocalFileDocumentSource(tmp_path / "docs", content_store=store)

    acme_docs = asyncio.run(source.fetch(CompanyRef(company_id="acme", name="Acme")))
    beta_docs = asyncio.run(source.fetch(CompanyRef(company_id="beta", name="Beta")))

    assert acme_docs[0].doc_id != beta_docs[0].doc_id


def test_second_fetch_hits_the_content_cache_and_does_not_reparse(tmp_path, monkeypatch):
    _write_doc(tmp_path, "acme", DocType.ANNUAL_REPORT_10K, "report.txt", "Cached content check.")
    store = DocumentContentStore(tmp_path / "store")
    source = LocalFileDocumentSource(tmp_path / "docs", content_store=store)

    asyncio.run(source.fetch(CompanyRef(company_id="acme", name="Acme")))

    from arp.ingestion import local_files

    def boom(path):
        raise AssertionError("should not reparse on a cache hit")

    monkeypatch.setattr(local_files, "parse_file_to_text_with_pages", boom)

    # get_or_parse was given the (already-patched-away) parser as a
    # closure captured at call time inside _parse_and_identify, so this
    # confirms the *store's* cache -- not just a Python-level memoization
    # -- is what avoids the reparse.
    docs = asyncio.run(source.fetch(CompanyRef(company_id="acme", name="Acme")))
    assert docs[0].full_text == "Cached content check."


def test_grounding_resolves_the_page_from_cached_page_breaks(tmp_path, monkeypatch):
    fake_pages = ["Page one intro.", "Revenue grew due to green capex investment."]
    monkeypatch.setattr(local_files, "_docling_converter", lambda: _FakeDoclingConverter(fake_pages))

    doc_dir = tmp_path / "docs" / "acme" / DocType.ANNUAL_REPORT_10K.value
    doc_dir.mkdir(parents=True)
    (doc_dir / "report.pdf").write_bytes(b"%PDF-1.4 fake bytes, to_markdown is mocked")

    store = DocumentContentStore(tmp_path / "store")
    source = LocalFileDocumentSource(tmp_path / "docs", content_store=store)

    docs = asyncio.run(source.fetch(CompanyRef(company_id="acme", name="Acme")))
    assert len(docs) == 1
    doc = docs[0]

    citation = Citation(doc_id=doc.doc_id, doc_type=DocType.ANNUAL_REPORT_10K, quote="Revenue grew due to green capex investment.")
    grounded = ground_citations([citation], {doc.doc_id: doc})

    assert grounded[0].grounded is True
    assert grounded[0].page == 2

    # A second fetch (a later run) re-derives the same doc_id and serves
    # the parsed text from the store, so the same citation still resolves
    # -- the cross-run resolution this whole store exists for.
    docs_again = asyncio.run(source.fetch(CompanyRef(company_id="acme", name="Acme")))
    grounded_again = ground_citations([citation], {docs_again[0].doc_id: docs_again[0]})
    assert grounded_again[0].grounded is True
    assert grounded_again[0].page == 2


def test_disabled_store_still_derives_a_stable_doc_id_but_never_caches_the_parse(tmp_path, monkeypatch):
    _write_doc(tmp_path, "acme", DocType.ANNUAL_REPORT_10K, "report.txt", "Disabled-store text.")
    store = DocumentContentStore(tmp_path / "store", enabled=False)
    source = LocalFileDocumentSource(tmp_path / "docs", content_store=store)

    from arp.ingestion import local_files

    calls = []
    original = local_files.parse_file_to_text_with_pages

    def counting(path):
        calls.append(1)
        return original(path)

    monkeypatch.setattr(local_files, "parse_file_to_text_with_pages", counting)

    first = asyncio.run(source.fetch(CompanyRef(company_id="acme", name="Acme")))
    second = asyncio.run(source.fetch(CompanyRef(company_id="acme", name="Acme")))

    # doc_id is still deterministic (content-key derived), even with
    # caching switched off entirely -- only persistence is disabled.
    assert first[0].doc_id == second[0].doc_id
    assert len(calls) == 2  # but every fetch reparses -- nothing is cached


def test_max_concurrent_parses_bounds_in_flight_parses(tmp_path):
    for i in range(6):
        _write_doc(tmp_path, "acme", DocType.ANNUAL_REPORT_10K, f"doc{i}.txt", f"Report number {i}.")

    store = DocumentContentStore(tmp_path / "store")
    source = LocalFileDocumentSource(tmp_path / "docs", content_store=store, max_concurrent_parses=2)

    in_flight = 0
    max_in_flight = 0
    orig = source._parse_and_identify

    def tracking(*args, **kwargs):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        try:
            return orig(*args, **kwargs)
        finally:
            in_flight -= 1

    source._parse_and_identify = tracking

    docs = asyncio.run(source.fetch(CompanyRef(company_id="acme", name="Acme")))

    assert len(docs) == 6
    assert max_in_flight <= 2
