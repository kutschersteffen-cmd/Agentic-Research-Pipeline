import pytest

from arp.compute import client as compute_client
from arp.ingestion import local_files
from arp.ingestion.local_files import parse_file_to_text_with_pages, parser_version
from arp.storage.document_store import DocumentContentStore
from tests.postgres_helpers import pg_dsn


def _no_cloud(path, version):
    pytest.fail("parse_pdf called")


def test_pdf_uses_remote_result(monkeypatch, tmp_path):  # AC-3 through the real entry point
    monkeypatch.setattr(compute_client, "parse_pdf", lambda p, v: ("T", [0], []))
    monkeypatch.setattr(local_files, "_convert", lambda p: pytest.fail("docling called"))
    assert parse_file_to_text_with_pages(tmp_path / "x.pdf") == ("T", [0], [])


def test_docx_stays_local(monkeypatch, tmp_path):  # AC-15
    monkeypatch.setattr(compute_client, "parse_pdf", _no_cloud)
    monkeypatch.setattr(local_files, "_extract_docx_text", lambda p: ("D", []))
    assert parse_file_to_text_with_pages(tmp_path / "x.docx") == ("D", [], [])


@pytest.mark.usefixtures("pg")
def test_cloud_result_is_cached(monkeypatch, tmp_path):  # AC-39
    calls = []
    monkeypatch.setattr(compute_client, "parse_pdf", lambda p, v: calls.append(v) or ("T", [0], []))
    path = tmp_path / "x.pdf"
    path.write_bytes(b"%PDF-1.4 cached")
    store = DocumentContentStore(tmp_path / "store", dsn=pg_dsn())
    for _ in range(2):
        parsed = store.get_or_parse(path, parser_version=parser_version(), parse=parse_file_to_text_with_pages)
    assert calls == [parser_version()]
    entry = store.lookup(store.content_key_for_file(path), parser_version())
    assert entry.full_text == "T" and parsed.full_text == "T"


@pytest.mark.usefixtures("pg")
def test_cache_hit_sends_nothing(monkeypatch, tmp_path):  # AC-14
    path = tmp_path / "x.pdf"
    path.write_bytes(b"%PDF-1.4 hit")
    store = DocumentContentStore(tmp_path / "store", dsn=pg_dsn())
    store.get_or_parse(path, parser_version=parser_version(), parse=lambda p: ("cached", [0], []))
    monkeypatch.setattr(compute_client, "parse_pdf", _no_cloud)
    parsed = store.get_or_parse(path, parser_version=parser_version(), parse=parse_file_to_text_with_pages)
    assert parsed.full_text == "cached"
