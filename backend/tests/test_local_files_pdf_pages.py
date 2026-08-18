import pymupdf4llm

from arp.ingestion.local_files import parse_file_to_text_with_pages


def test_pdf_page_breaks_mark_the_start_of_each_page(monkeypatch, tmp_path):
    fake_pages = [
        {"text": "Page one text."},
        {"text": "Page two text, a bit longer than the first."},
        {"text": "Page three."},
    ]
    monkeypatch.setattr(pymupdf4llm, "to_markdown", lambda *args, **kwargs: fake_pages)

    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.4 fake bytes, never actually parsed since to_markdown is mocked")

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


def _build_pdf_with_a_table(path):
    """A real PDF (no mocking) with a grid-lined table -- the shape a
    disclosure PDF's segment/GHG/revenue table typically has -- so this
    test exercises MuPDF's actual table detector, not just the page-join
    bookkeeping around it."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    rows = [("Segment", "Revenue", "OpInc"), ("Auto", "500", "50"), ("Software", "300", "90")]
    y = 70
    for row in rows:
        x = 50
        for cell in row:
            page.insert_text((x, y), cell)
            x += 100
        y += 20
    for i in range(4):
        page.draw_line((50, 60 + i * 20), (350, 60 + i * 20))
    for i in range(4):
        page.draw_line((50 + i * 100, 60), (50 + i * 100, 120))
    doc.save(str(path))


def test_table_in_pdf_is_rendered_as_a_markdown_table(tmp_path):
    path = tmp_path / "segments.pdf"
    _build_pdf_with_a_table(path)

    text, _page_breaks = parse_file_to_text_with_pages(path)

    assert "|Segment|Revenue|OpInc|" in text
    assert "|Auto|500|50|" in text
    assert "|Software|300|90|" in text
