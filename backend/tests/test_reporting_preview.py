import shutil

import pytest

from arp.reporting.deck_builder import build_deck
from arp.reporting.pdf_builder import build_pdf
from arp.reporting.preview import ensure_preview_images
from arp.schemas.reporting import (
    ContentItem,
    LayoutInstructions,
    OutputFormat,
    ReportPlan,
    ReportSection,
)

_HAS_PDFTOPPM = shutil.which("pdftoppm") is not None
_HAS_SOFFICE = shutil.which("soffice") is not None


def _plan() -> ReportPlan:
    return ReportPlan(
        title="Preview Test",
        subtitle="",
        sections=[ReportSection(heading="Only section", narrative=[ContentItem(text="a point")])],
    )


@pytest.mark.skipif(not _HAS_PDFTOPPM, reason="pdftoppm not installed")
def test_pdf_source_renders_one_png_per_page(tmp_path):
    pdf_path = tmp_path / "report.pdf"
    build_pdf(_plan(), [], LayoutInstructions(), pdf_path)

    pages = ensure_preview_images(pdf_path, tmp_path / "preview", OutputFormat.PDF)

    assert len(pages) >= 1
    assert all(p.exists() and p.suffix == ".png" for p in pages)


@pytest.mark.skipif(not _HAS_PDFTOPPM, reason="pdftoppm not installed")
def test_unchanged_source_is_served_from_cache(tmp_path, monkeypatch):
    pdf_path = tmp_path / "report.pdf"
    build_pdf(_plan(), [], LayoutInstructions(), pdf_path)
    preview_dir = tmp_path / "preview"

    first = ensure_preview_images(pdf_path, preview_dir, OutputFormat.PDF)

    def _boom(cmd):
        raise AssertionError(f"should not re-run {cmd[0]} for a cache hit")

    monkeypatch.setattr("arp.reporting.preview._run", _boom)
    second = ensure_preview_images(pdf_path, preview_dir, OutputFormat.PDF)

    assert second == first


@pytest.mark.skipif(not (_HAS_SOFFICE and _HAS_PDFTOPPM), reason="soffice/pdftoppm not installed")
def test_pptx_source_goes_through_soffice_then_pdftoppm(tmp_path):
    pptx_path = tmp_path / "deck.pptx"
    build_deck(_plan(), [], LayoutInstructions(), None, pptx_path)

    pages = ensure_preview_images(pptx_path, tmp_path / "preview", OutputFormat.PPTX)

    # title slide + agenda slide + 1 section slide
    assert len(pages) == 3
