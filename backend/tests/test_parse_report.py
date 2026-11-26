"""Parse report: local_files.parse_file_with_report and its column in the parsed-text cache."""

import asyncio
import hashlib
import sqlite3

import pytest
from reportlab.pdfgen import canvas

from arp.ingestion import local_files
from arp.ingestion.local_files import (
    LocalFileDocumentSource,
    parse_file_to_text_with_pages,
    parse_file_with_report,
    parser_version,
)
from arp.schemas.common import CompanyRef, DocType, TableSpan
from arp.storage.document_store import DocumentContentStore
from tests.postgres_helpers import pg_dsn

P1 = "A" * 80
P2 = "  short page  "
T1 = "| a | b |\n|---|---|\n| 1 | 2 |"
P3 = T1 + "\n\n" + "B" * 60
T_MISSING = "| zz | yy |\n|---|---|\n| 9 | 9 |"


class _Data:
    table_cells = []


class _FakeTable:
    data = _Data()

    def __init__(self, md):
        self._md = md

    def export_to_markdown(self, doc):
        return self._md

    def caption_text(self, doc):
        return ""


class _FakeDoc:
    def __init__(self, pages, tables, whole=None):
        self._pages = pages
        self._whole = whole
        self.pages = {i + 1: object() for i in range(len(pages))}
        self.tables = [_FakeTable(t) for t in tables]

    def export_to_markdown(self, page_no=None):
        return self._whole if page_no is None else self._pages[page_no - 1]


class _FakeConverter:
    def __init__(self, doc):
        self._doc = doc

    def convert(self, path):
        return type("R", (), {"document": self._doc})()


def _fake_docling(monkeypatch, tables=(T1, T_MISSING), text_layer=True, whole=None):
    doc = _FakeDoc([P1, P2, P3], list(tables), whole)
    monkeypatch.setattr(local_files, "_docling_converter", lambda ocr=True: _FakeConverter(doc))
    monkeypatch.setattr(local_files, "_has_text_layer", lambda path: text_layer)


def _pdf(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path))
    c.drawString(72, 700, "Revenue grew due to green capex investment this year.")
    c.save()
    return path


def _without_seconds(report):
    return {k: v for k, v in report.items() if k != "parse_seconds"}


PDF3_REPORT = {
    "parser": "docling", "page_count": 3, "short_pages": [2], "ocr": False, "tables_found": 2, "tables_kept": 1,
}


def test_pdf_report(monkeypatch, tmp_path):  # AC-31
    _fake_docling(monkeypatch)
    out = parse_file_with_report(_pdf(tmp_path / "r.pdf"))
    assert len(out) == 4
    report = out[3]
    assert set(report) == {"parser", "parser_version", "page_count", "short_pages", "ocr", "tables_found",
                           "tables_kept", "parse_seconds"}
    assert _without_seconds(report) == {**PDF3_REPORT, "parser_version": parser_version()}
    assert isinstance(report["parse_seconds"], float) and report["parse_seconds"] >= 0
    assert round(report["parse_seconds"], 2) == report["parse_seconds"]


def test_all_tables_kept(monkeypatch, tmp_path):  # AC-32
    _fake_docling(monkeypatch, tables=(T1,))
    report = parse_file_with_report(_pdf(tmp_path / "r.pdf"))[3]
    assert report["tables_found"] == report["tables_kept"] == 1


def test_ocr_recorded(monkeypatch, tmp_path):  # AC-33
    _fake_docling(monkeypatch, text_layer=False)
    assert parse_file_with_report(_pdf(tmp_path / "r.pdf"))[3]["ocr"] is True


def test_parse_output_unchanged(monkeypatch, tmp_path):  # AC-34
    _fake_docling(monkeypatch)
    path = _pdf(tmp_path / "r.pdf")
    text, page_breaks, spans = parse_file_to_text_with_pages(path)
    assert tuple(parse_file_with_report(path)[:3]) == (text, page_breaks, spans)
    assert text == "\n\n".join([P1, P2, P3])
    assert page_breaks == [0, 82, 98]
    assert len(spans) == 1 and text[spans[0].char_start : spans[0].char_end] == T1


def test_compute_report(monkeypatch, tmp_path):  # AC-35
    result = ("A" * 80 + "\n\ntiny", [0, 82], [TableSpan(table_id="table_0", char_start=0, char_end=10)])
    monkeypatch.setattr(local_files.compute_client, "parse_pdf", lambda p, v: result)
    out = parse_file_with_report(tmp_path / "r.pdf")
    assert tuple(out[:3]) == result
    assert _without_seconds(out[3]) == {
        "parser": "compute", "parser_version": parser_version(), "page_count": 2, "short_pages": [2], "ocr": None,
        "tables_found": None, "tables_kept": 1,
    }


@pytest.mark.parametrize(("name", "parser"), [("a.txt", "text"), ("a.html", "html")])
def test_other_formats(tmp_path, name, parser):  # AC-36
    path = tmp_path / name
    path.write_text("<p>Hello there</p>" if parser == "html" else "Hello there")
    assert _without_seconds(parse_file_with_report(path)[3]) == {
        "parser": parser, "parser_version": parser_version(), "page_count": None, "short_pages": [], "ocr": None,
        "tables_found": None, "tables_kept": 0,
    }


def test_docx_report(monkeypatch, tmp_path):  # AC-44
    _fake_docling(monkeypatch, whole="Intro\n\n" + T1)
    report = parse_file_with_report(tmp_path / "a.docx")[3]
    assert _without_seconds(report) == {
        "parser": "docling", "parser_version": parser_version(), "page_count": None, "short_pages": [], "ocr": False,
        "tables_found": 2, "tables_kept": 1,
    }


def _raise(path):
    raise AssertionError("parse must not run on a cache hit")


@pytest.mark.usefixtures("pg")
def test_report_stored_and_returned_on_hit(monkeypatch, tmp_path):  # AC-37, AC-38
    _fake_docling(monkeypatch)
    store = DocumentContentStore(tmp_path / "store", dsn=pg_dsn())
    path = _pdf(tmp_path / "r.pdf")
    first = store.get_or_parse(path, parser_version=parser_version(), parse=parse_file_with_report)
    assert _without_seconds(first.parse_report) == {**PDF3_REPORT, "parser_version": parser_version()}
    assert store.lookup(store.content_key_for_file(path), parser_version()).parse_report == first.parse_report
    second = store.get_or_parse(path, parser_version=parser_version(), parse=_raise)
    assert second.parse_report == first.parse_report


@pytest.mark.usefixtures("pg")
def test_rows_without_report(monkeypatch, tmp_path):  # AC-39
    _fake_docling(monkeypatch)
    store = DocumentContentStore(tmp_path / "store", dsn=pg_dsn())
    path = _pdf(tmp_path / "r.pdf")
    text, page_breaks, spans = parse_file_to_text_with_pages(path)
    store.get_or_parse(path, parser_version=parser_version(), parse=parse_file_to_text_with_pages)
    parsed = store.lookup(store.content_key_for_file(path), parser_version())
    assert parsed.parse_report is None
    assert (parsed.full_text, parsed.page_breaks, parsed.table_spans) == (text, page_breaks, [s.model_dump() for s in spans])
    store.store("k2", key_kind="file_bytes", parser_version="v", source_suffix=".txt", byte_size=1, text="hi",
                page_breaks=[])
    other = store.lookup("k2", "v")
    assert other.parse_report is None and other.full_text == "hi" and other.page_breaks == []


@pytest.mark.usefixtures("pg")
def test_legacy_table_stays_valid(tmp_path):  # AC-40
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    path = tmp_path / "a.txt"
    path.write_text("cached text")
    key = hashlib.sha256(path.read_bytes()).hexdigest()
    conn = sqlite3.connect(store_dir / "content.db")
    conn.executescript("""
        CREATE TABLE parsed_content (
            id INTEGER PRIMARY KEY, content_key TEXT NOT NULL, key_kind TEXT NOT NULL, parser_version TEXT NOT NULL,
            source_suffix TEXT NOT NULL, full_text TEXT NOT NULL, page_breaks TEXT NOT NULL DEFAULT '[]',
            table_spans TEXT NOT NULL DEFAULT '[]', text_sha256 TEXT NOT NULL, char_len INTEGER NOT NULL,
            byte_size INTEGER NOT NULL, created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX ix_parsed_content_key ON parsed_content (content_key, parser_version);
    """)
    conn.execute(
        "INSERT INTO parsed_content (content_key, key_kind, parser_version, source_suffix, full_text, page_breaks, "
        "table_spans, text_sha256, char_len, byte_size, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (key, "file_bytes", parser_version(), ".txt", "old text", "[0]", "[]", "x", 8, 11, "2026-01-01"),
    )
    conn.commit()
    conn.close()
    store = DocumentContentStore(store_dir, dsn=pg_dsn())
    parsed = store.get_or_parse(path, parser_version=parser_version(), parse=_raise)
    assert (parsed.full_text, parsed.page_breaks, parsed.table_spans, parsed.parse_report) == ("old text", [0], [], None)


@pytest.mark.usefixtures("pg")
def test_local_source_stores_report(monkeypatch, tmp_path):  # AC-41
    _fake_docling(monkeypatch)
    store = DocumentContentStore(tmp_path / "store", dsn=pg_dsn())
    docs = tmp_path / "docs"
    path = _pdf(docs / "acme" / DocType.ANNUAL_REPORT_10K.value / "report.pdf")
    source = LocalFileDocumentSource(docs, content_store=store)
    [doc] = asyncio.run(source.fetch(CompanyRef(company_id="acme", name="Acme")))
    assert doc.full_text == "\n\n".join([P1, P2, P3])
    assert store.lookup(store.content_key_for_file(path), parser_version()).parse_report["tables_found"] == 2


def test_parser_version_unchanged():  # AC-42
    assert parser_version().startswith("logic=3|")
