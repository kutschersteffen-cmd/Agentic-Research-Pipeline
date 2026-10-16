import pytest
from fastapi import HTTPException
from reportlab.pdfgen import canvas

from arp.api.routers.documents import get_document_page, get_document_page_boxes
from arp.config import Settings
from arp.ingestion.pdf_page import find_boxes, render_page
from arp.schemas.common import DocType


@pytest.fixture
def docs_dir(tmp_path):
    folder = tmp_path / "docs" / "c1" / DocType.SUSTAINABILITY_REPORT.value
    folder.mkdir(parents=True)
    c = canvas.Canvas(str(folder / "report.pdf"))  # A4: 595 x 842 pt
    c.drawString(72, 720, "Introduction and strategy overview.")
    c.showPage()
    c.drawString(72, 720, "Spills: 7 incidents in FY2024.")
    c.drawString(72, 700, "Scope 1 emissions 1,234.5 tCO2e")
    c.showPage()
    c.save()
    (folder / "notes.txt").write_text("not a pdf")
    return tmp_path / "docs"


def _pdf(docs_dir) -> str:
    return str(docs_dir / "c1" / DocType.SUSTAINABILITY_REPORT.value / "report.pdf")


def test_whole_text_is_boxed_as_page_fractions(docs_dir):
    [box] = find_boxes(_pdf(docs_dir), 2, "Spills: 7  incidents\nin FY2024.")
    assert 0.11 < box["l"] < 0.13 and box["l"] < box["r"] < 1  # starts at x=72pt of 595
    assert 0.12 < box["t"] < box["b"] < 0.16  # baseline y=720pt of 842, measured from the top


def test_a_markdown_table_cell_falls_back_to_its_numbers(docs_dir):
    boxes = find_boxes(_pdf(docs_dir), 2, "| Scope 1 | **1,234.5** | 2024 |")
    assert len(boxes) == 1
    assert 0.15 < boxes[0]["t"] < 0.18  # the 1,234.5 line (y=700pt), not the spills line


def test_no_match_or_no_page_gives_no_boxes(docs_dir):
    assert find_boxes(_pdf(docs_dir), 2, "Water withdrawal 88 ML") == []
    assert find_boxes(_pdf(docs_dir), 2, "| 7 | 2024 |") == []  # short numbers and years never match alone
    assert find_boxes(_pdf(docs_dir), 9, "Spills") == []


def test_page_endpoints(docs_dir):
    settings = Settings(documents_dir=docs_dir)
    t = DocType.SUSTAINABILITY_REPORT
    png = get_document_page("c1", t, "report.pdf", 2, settings)
    assert (png.media_type, png.body[:4]) == ("image/png", b"\x89PNG")
    assert render_page(_pdf(docs_dir), 2)[:4] == b"\x89PNG"
    assert len(get_document_page_boxes("c1", t, "report.pdf", 2, "Spills: 7", settings)["boxes"]) == 1
    for call, status in (
        (lambda: get_document_page("c1", t, "report.pdf", 3, settings), 404),
        (lambda: get_document_page("c1", t, "notes.txt", 1, settings), 400),
        (lambda: get_document_page_boxes("c1", t, "../report.pdf", 1, "x", settings), 400),
    ):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == status


def test_concurrent_calls_do_not_crash(docs_dir):
    """pdfium is not thread-safe: unserialized, parallel API requests segfaulted the server."""
    from concurrent.futures import ThreadPoolExecutor

    def work(i):
        return render_page(_pdf(docs_dir), 2)[:4] if i % 2 else len(find_boxes(_pdf(docs_dir), 2, "Spills: 7"))

    with ThreadPoolExecutor(8) as pool:
        assert set(pool.map(work, range(200))) == {b"\x89PNG", 1}
