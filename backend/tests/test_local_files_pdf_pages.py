from arp.ingestion.local_files import parse_file_to_text_with_pages


class _FakePage:
    def __init__(self, text: str):
        self._text = text

    def extract_text(self):
        return self._text


class _FakeReader:
    is_encrypted = False

    def __init__(self, _path):
        self.pages = [
            _FakePage("Page one text."),
            _FakePage("Page two text, a bit longer than the first."),
            _FakePage("Page three."),
        ]


def test_pdf_page_breaks_mark_the_start_of_each_page(monkeypatch, tmp_path):
    monkeypatch.setattr("pypdf.PdfReader", _FakeReader)

    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.4 fake bytes, never actually parsed since PdfReader is mocked")

    text, page_breaks = parse_file_to_text_with_pages(path)

    page1, page2, page3 = "Page one text.", "Page two text, a bit longer than the first.", "Page three."
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
