from arp.ingestion import local_files
from arp.ingestion.local_files import parse_file_to_text_with_pages


class _FakeDoclingDocument:
    """Minimal stand-in for a docling DoclingDocument: enough surface
    (`.pages` keyed by 1-based page number, `.export_to_markdown(page_no=)`)
    for _extract_pdf_text's page-join loop, without invoking Docling's real
    ML pipeline (which needs a one-time model download from Hugging Face
    Hub and is far too slow/network-dependent for a unit test)."""

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


def test_pdf_page_breaks_mark_the_start_of_each_page(monkeypatch, tmp_path):
    page1 = "Page one text."
    page2 = "Page two text, a bit longer than the first."
    page3 = "Page three."
    monkeypatch.setattr(local_files, "_docling_converter", lambda: _FakeDoclingConverter([page1, page2, page3]))

    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.4 fake bytes, never actually parsed since the converter is mocked")

    text, page_breaks = parse_file_to_text_with_pages(path)

    assert text == "\n\n".join([page1, page2, page3])
    assert page_breaks == [0, len(page1) + 2, len(page1) + 2 + len(page2) + 2]
    # each recorded offset actually lands on that page's first character
    assert text[page_breaks[0] :].startswith(page1)
    assert text[page_breaks[1] :].startswith(page2)
    assert text[page_breaks[2] :].startswith(page3)


def test_non_pdf_formats_return_empty_page_breaks(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("Just some plain text, no pagination concept.")

    text, page_breaks = parse_file_to_text_with_pages(path)

    assert text == "Just some plain text, no pagination concept."
    assert page_breaks == []


def test_table_markdown_from_docling_passes_through_unmangled(monkeypatch, tmp_path):
    """Docling's TableFormer model is what turns a disclosure PDF's
    grid-lined table into real markdown -- that model requires a network
    download and real inference, so it's out of scope for a unit test.
    This test only proves _extract_pdf_text passes a page's markdown
    (table included) through untouched into the joined document text."""
    table_markdown = (
        "| Segment | Revenue | OpInc |\n"
        "| --- | --- | --- |\n"
        "| Auto | 500 | 50 |\n"
        "| Software | 300 | 90 |"
    )
    monkeypatch.setattr(local_files, "_docling_converter", lambda: _FakeDoclingConverter([table_markdown]))

    path = tmp_path / "segments.pdf"
    path.write_bytes(b"%PDF-1.4 fake bytes, never actually parsed since the converter is mocked")

    text, _page_breaks = parse_file_to_text_with_pages(path)

    assert "| Segment | Revenue | OpInc |" in text
    assert "| Auto | 500 | 50 |" in text
    assert "| Software | 300 | 90 |" in text
