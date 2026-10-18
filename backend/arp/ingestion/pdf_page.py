"""One PDF page as a PNG, and where a piece of text sits on it.

Boxes come from the PDF's own text layer at view time (pdfium search), not from the parse: the stored
text is Docling markdown, whose offsets don't map back onto the page, and this way every stored
document gets boxes without a re-parse."""

from __future__ import annotations

import io
import re

from docling.utils.locks import pypdfium2_lock

_SCALE = 2.0  # 144 dpi: table digits stay legible, the image stays under the model's size limit
_MAX_BOXES = 20
_MARKDOWN = re.compile(r"[|*#]+")
_NUMBER = re.compile(r"\d+(?:[.,'\u00a0 ]\d{3})*(?:[.,]\d+)?")  # "1 234,5" is one number, "1 1,234" two
_YEAR = re.compile(r"(19|20)\d\d")


def render_page(pdf_path: str, page: int) -> bytes | None:
    """1-indexed `page` as PNG bytes; None when the page doesn't exist."""
    import pypdfium2  # docling's own PDF backend, so always installed

    with pypdfium2_lock:  # pdfium is not thread-safe; docling's own lock also guards its parses
        pdf = pypdfium2.PdfDocument(pdf_path)
        try:
            if not 1 <= page <= len(pdf):
                return None
            buf = io.BytesIO()
            pdf[page - 1].render(scale=_SCALE).to_pil().save(buf, format="PNG")
            return buf.getvalue()
        finally:
            pdf.close()


def _needles(text: str) -> list[str]:
    """The whole text first; failing that, its numbers (a markdown table cell rarely matches the
    PDF's text run as a whole, its figures do). Short numbers and years would match everywhere."""
    whole = " ".join(_MARKDOWN.sub(" ", text).split())
    numbers = [n.strip() for n in _NUMBER.findall(whole)]
    return [whole, *dict.fromkeys(n for n in numbers if sum(c.isdigit() for c in n) >= 3 and not _YEAR.fullmatch(n))]


def find_boxes(pdf_path: str, page: int, text: str) -> list[dict]:
    """Boxes around `text` on the 1-indexed page, as fractions of the page (top-left origin):
    [{"l", "t", "r", "b"}]. The whole text if it matches, else every match of its numbers.
    Empty when the page doesn't exist or nothing matches."""
    import pypdfium2

    with pypdfium2_lock:  # pdfium is not thread-safe; docling's own lock also guards its parses
        pdf = pypdfium2.PdfDocument(pdf_path)
        try:
            if not 1 <= page <= len(pdf):
                return []
            p = pdf[page - 1]
            rotation = p.get_rotation()
            w, h = p.get_size()  # as displayed, so swapped on a quarter-turned page
            if rotation in (90, 270):
                w, h = h, w
            tp = p.get_textpage()
            whole, *numbers = _needles(text)
            found = _boxes_for(tp, whole, w, h) if whole else []
            if not found:
                found = [b for n in numbers for b in _boxes_for(tp, n, w, h)]
            return [_rotated(b, rotation) for b in found[:_MAX_BOXES]]
        finally:
            pdf.close()


def _rotated(b: dict, rotation: int) -> dict:
    """A box on the unrotated page turned clockwise by the page's /Rotate, as the rendered image shows it."""
    if rotation == 90:
        return {"l": 1 - b["b"], "t": b["l"], "r": 1 - b["t"], "b": b["r"]}
    if rotation == 180:
        return {"l": 1 - b["r"], "t": 1 - b["b"], "r": 1 - b["l"], "b": 1 - b["t"]}
    if rotation == 270:
        return {"l": b["t"], "t": 1 - b["r"], "r": b["b"], "b": 1 - b["l"]}
    return b


def _boxes_for(tp, needle: str, w: float, h: float) -> list[dict]:
    """Boxes in fractions of the unrotated page: pdfium reports text rects before the page's /Rotate."""
    out = []
    searcher = tp.search(needle)
    while hit := searcher.get_next():
        for k in range(tp.count_rects(*hit)):
            left, bottom, right, top = tp.get_rect(k)
            out.append({"l": left / w, "t": 1 - top / h, "r": right / w, "b": 1 - bottom / h})
    return out
