from __future__ import annotations

import asyncio
import sqlite3

from arp.ingestion.doc_identity import assign_identity, published_at_for, reporting_year
from arp.ingestion.local_files import LocalFileDocumentSource
from arp.schemas.common import CompanyRef, DocType, SourceDocument
from arp.schemas.discovery import CaptureRecord
from arp.storage.document_store import DocumentContentStore

ACME = CompanyRef(company_id="acme", name="Acme")
BODY = "Acme emitted 100 tonnes of CO2 in 2023. " * 20


def _fetch(tmp_path, store):
    return asyncio.run(LocalFileDocumentSource(tmp_path / "docs", content_store=store).fetch(ACME))


def test_corrected_republication_links_to_first(tmp_path):
    folder = tmp_path / "docs" / "acme" / DocType.SUSTAINABILITY_REPORT.value
    folder.mkdir(parents=True)
    store = DocumentContentStore(tmp_path / "store")
    (folder / "Sustainability Report 2023.txt").write_text(BODY)
    (first,) = _fetch(tmp_path, store)
    (folder / "Sustainability Report 2023 corrected.txt").write_text(BODY + "Corrected figure: 90 tonnes.")
    docs = {d.title: d for d in _fetch(tmp_path, store)}
    second = docs["Sustainability Report 2023 corrected.txt"]
    assert second.family_id == first.family_id
    assert second.version == 2
    assert second.supersedes == first.doc_id
    assert store.resolve_document(first.doc_id).version == 1
    assert docs["Sustainability Report 2023.txt"].version == 1


def _assign(title, text="", published_at=None, members=()):
    return assign_identity(
        doc_id="doc_abcdef0123456789", company_id="acme", doc_type="sustainability_report",
        title=title, text=text, published_at=published_at, family=lambda fid: list(members),
    )


def test_no_year_goes_to_review():
    d = _assign("Report.pdf", "no year here")
    assert d.needs_review is True and d.confidence == 0.3 and d.version == 1
    assert d.family_id == "fam_abcdef0123456789"


def test_same_year_no_marker_no_dates_is_low_confidence():
    from arp.storage.document_registry import StoredDocumentRef

    prev = StoredDocumentRef("doc_1", "acme", "sustainability_report", "k", "R 2023", None, None, version=1)
    d = _assign("Report 2023 final.pdf", members=[prev])
    assert d.confidence == 0.5 and d.needs_review and d.version == 2 and d.supersedes == "doc_1"


def test_two_years_in_title_is_ambiguous():
    assert reporting_year("Report 2022 vs 2023", "") is None
    assert reporting_year("Report", "intro 2021 and 2022") == 2021


def test_published_at_from_capture_header(tmp_path):
    cap = CaptureRecord(
        trigger="t", url_chain=["u"], status=200, headers={"Last-Modified": "Wed, 01 Mar 2023 10:00:00 GMT"},
        content_key="k", storage_uri=None, rights_tag="x",
    )
    assert published_at_for(tmp_path / "missing.txt", cap) == "2023-03-01"
    assert published_at_for(tmp_path / "missing.txt", None) is None


def test_old_content_db_gains_identity_columns(tmp_path):
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    conn = sqlite3.connect(store_dir / "content.db")
    conn.execute(
        "CREATE TABLE documents (doc_id TEXT PRIMARY KEY, company_id TEXT NOT NULL, doc_type TEXT NOT NULL, "
        "content_key TEXT NOT NULL, title TEXT NOT NULL, local_path TEXT, source_url TEXT, "
        "first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO documents VALUES ('doc_old','acme','10-K','k','T',NULL,NULL,'a','b')")
    conn.commit()
    conn.close()
    store = DocumentContentStore(store_dir)
    ref = store.resolve_document("doc_old")
    assert ref.family_id is None and ref.version is None


def test_old_source_document_json_loads():
    d = SourceDocument.model_validate({"company_id": "a", "doc_type": "other", "title": "t", "full_text": "x"})
    assert d.family_id is None and d.version is None and d.content_key is None


def test_first_ingest_order_is_deterministic_under_reverse_completion(tmp_path, monkeypatch):
    import time

    from arp.ingestion import local_files

    folder = tmp_path / "docs" / "acme" / DocType.SUSTAINABILITY_REPORT.value
    folder.mkdir(parents=True)
    (folder / "Sustainability Report 2023.txt").write_text(BODY)
    (folder / "Sustainability Report 2023 corrected.txt").write_text(BODY + "Corrected figure.")
    real = local_files.parse_file_to_text_with_pages

    def slow_original(path):
        if "corrected" not in path.name:
            time.sleep(0.3)  # the original finishes parsing last
        return real(path)

    monkeypatch.setattr(local_files, "parse_file_to_text_with_pages", slow_original)
    for i in range(2):
        store = DocumentContentStore(tmp_path / f"store{i}")
        docs = {d.title: d for d in _fetch(tmp_path, store)}
        orig, corr = docs["Sustainability Report 2023.txt"], docs["Sustainability Report 2023 corrected.txt"]
        assert orig.version == 1 and corr.version == 2 and corr.supersedes == orig.doc_id
