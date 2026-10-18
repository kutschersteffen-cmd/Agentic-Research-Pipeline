"""reportlab builders for the spec's document-check fixtures P1-P4."""

from __future__ import annotations

from pathlib import Path

from reportlab.pdfgen import canvas


def make_pdf(path: Path, pages: list[str], n_pages: int = 30) -> Path:
    """`n_pages` pages; page i gets `pages[i]` (one drawn line per text line), pages beyond the list are blank."""
    c = canvas.Canvas(str(path))
    for i in range(n_pages):
        text = pages[i] if i < len(pages) else ""
        for row, line in enumerate(text.splitlines()):
            c.drawString(72, 760 - 14 * row, line)
        c.showPage()
    c.save()
    return path


def make_image_pdf(path: Path, n_pages: int = 30) -> Path:
    """`n_pages` pages, each with one drawn rectangle and no text layer."""
    c = canvas.Canvas(str(path))
    for _ in range(n_pages):
        c.rect(72, 72, 300, 400, fill=1)
        c.showPage()
    c.save()
    return path


# Neutral body text so a fixture has enough text not to read as image-only.
FILLER = "\n".join(["The group's revenue and operating result developed in line with the forecast."] * 4)


def p1(path: Path) -> Path:
    pages = ["Testwerke AG Geschäftsbericht 2025", FILLER] + [""] * 25 + ["LEI: 5299009TESTWERKE0063"]
    return make_pdf(path, pages)


def p2(path: Path) -> Path:
    return make_pdf(path, ["Testwerke AG Annual Report 2025", FILLER])


def p3(path: Path) -> Path:
    return make_pdf(path, ["Otherco plc Annual Report 2025", FILLER])


def p4(path: Path) -> Path:
    return make_image_pdf(path)
