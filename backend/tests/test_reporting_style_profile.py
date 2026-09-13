from pptx import Presentation

from arp.reporting.style_profile import extract_style_profile, ingest_template
from arp.storage.reporting_store import ReportingStore


def _make_blank_pptx(path) -> None:
    Presentation().save(str(path))


def test_extract_style_profile_reads_layouts_and_theme(tmp_path):
    pptx_path = tmp_path / "template.pptx"
    _make_blank_pptx(pptx_path)

    style = extract_style_profile(pptx_path, "template.pptx")

    assert style.source_filename == "template.pptx"
    assert style.slide_width_emu > 0
    assert style.slide_height_emu > 0
    layout_names = {layout.name for layout in style.layouts}
    assert "Title Slide" in layout_names
    assert any("title" in layout.placeholder_types for layout in style.layouts)
    # Default python-pptx template's Office theme ships known accent colors.
    assert style.theme_colors.get("accent1") == "4F81BD"
    assert style.theme_colors.get("dk2") == "1F497D"
    assert style.major_font == "Calibri"


def test_ingest_template_persists_style_and_copies_original_file(tmp_path):
    pptx_path = tmp_path / "uploaded.pptx"
    _make_blank_pptx(pptx_path)
    store = ReportingStore(tmp_path / "reports", tmp_path / "templates")

    style = ingest_template(store, pptx_path, "uploaded.pptx")

    assert store.load_template_style(style.template_id) == style
    assert style.stored_path
    from pathlib import Path

    assert Path(style.stored_path).exists()
    assert style in store.list_template_styles()
