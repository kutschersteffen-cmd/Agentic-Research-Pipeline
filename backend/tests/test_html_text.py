import trafilatura

from arp.ingestion.html_text import extract_html_text

_PARA = "Capital expenditures for the steel mills segment were reviewed by the board during the year."


def _filing(pages: int) -> str:
    body = "".join(
        '<div style="position:relative">' +"".join(f"<div><span>Page {i}: {_PARA}</span></div>" for _ in range(6)) + "</div>"
        for i in range(pages)
    )
    return f"<html><body>{body}</body></html>"


def test_a_large_document_cut_to_its_cover_falls_back_to_the_full_text(monkeypatch):
    # Filing-agent 10-Ks wrap each printed page in its own block; trafilatura then keeps only the cover page.
    monkeypatch.setattr(trafilatura, "extract", lambda *a, **k: "FORM 10-K Nucor Corporation cover page")
    text = extract_html_text(_filing(pages=150))
    assert "Page 149:" in text
    assert len(text.split()) > 10_000


def test_a_short_web_page_keeps_trafilaturas_main_content(monkeypatch):
    # On ordinary pages trafilatura is right to drop navigation, even when that removes most of the words.
    page = "<html><body><nav>" + "Home About Investors Careers " * 200 + "</nav><p>" + _PARA + "</p></body></html>"
    monkeypatch.setattr(trafilatura, "extract", lambda *a, **k: _PARA)
    assert extract_html_text(page) == _PARA


def test_a_document_trafilatura_reads_in_full_is_unchanged():
    raw = _filing(pages=60)
    assert extract_html_text(raw) == trafilatura.extract(raw, favor_recall=True)


def test_a_document_trafilatura_declines_falls_back_to_the_full_text(monkeypatch):
    monkeypatch.setattr(trafilatura, "extract", lambda *a, **k: None)
    assert "Page 0:" in extract_html_text(_filing(pages=2))
