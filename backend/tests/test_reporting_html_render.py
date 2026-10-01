from arp.reporting.deck_compat import deck_from_plan
from arp.reporting.house_style import get_variant
from arp.reporting.html_render import render_deck_html
from arp.schemas.reporting import ChartSpec, Deck, ReportPlan, ReportSection, SlideContent
from tests.fixtures.stress_deck import stress_deck


def test_html_escapes_llm_text():
    deck = Deck(title="T", slides=[SlideContent(headline="<script>x</script> & {{ y }}", layout="bullets", variant="three",
                                                slots={"items": ["a & b"]})])
    html = render_deck_html(deck, [])
    assert "<script>x" not in html and "&lt;script&gt;" in html and "{{ y }}" in html


def test_deck_from_plan_maps_layout_hints():
    plan = ReportPlan(title="T", sections=[ReportSection(heading="S", layout_hint="section_header"),
                                           ReportSection(heading="C", layout_hint="chart_focus", chart=ChartSpec(dataset_id="d"))])
    d = deck_from_plan(plan)
    assert [(s.layout, s.variant) for s in d.slides] == [("title", "plain"), ("section", "default"), ("chart_takeaway", "full")]


def test_every_slot_has_data_attributes():
    deck, ds = stress_deck("min")
    html = render_deck_html(deck, ds)
    expected = sum(len(get_variant(s.layout, s.variant).slots) for s in deck.slides)
    assert html.count("data-slot=") - html.count('data-slot="headline"') == expected


_PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82")


def test_image_path_is_inlined_as_data_uri(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(_PNG)
    deck = Deck(title="T", slides=[SlideContent(headline="h", layout="image", variant="default", slots={"caption": "c"}, image_path=str(img))])
    assert "data:image/png;base64," in render_deck_html(deck, [])


def test_missing_image_raises(tmp_path):
    import pytest

    deck = Deck(title="T", slides=[SlideContent(headline="h", layout="image", variant="default", image_path=str(tmp_path / "no.png"))])
    with pytest.raises(FileNotFoundError, match="no.png"):
        render_deck_html(deck, [])


def _tokens_with_fonts(**fonts):
    from arp.reporting.house_style import load_tokens

    t = load_tokens()
    return t.model_copy(update={"fonts": t.fonts.model_copy(update=fonts)})


_ONE = Deck(title="T", slides=[SlideContent(headline="h", layout="bullets", variant="three", slots={"items": ["a"]})])


def test_token_font_with_a_file_is_embedded_as_data_uri():
    html = render_deck_html(_ONE, [], tokens=_tokens_with_fonts(heading="Geist, Arial, sans-serif", body="Geist, Arial", mono=None))
    assert "--font-heading: Geist, Arial, sans-serif" in html
    assert html.count("@font-face") == 2  # Geist-400/600, deduplicated across heading and body
    assert "font-family: 'Geist'; font-weight: 600" in html and "src: url(data:font/ttf;base64," in html


def test_quoted_font_token_is_not_html_escaped_inside_style():
    html = render_deck_html(_ONE, [], tokens=_tokens_with_fonts(heading="'Geist', Arial"))
    assert "--font-heading: 'Geist', Arial" in html


def test_token_font_without_a_file_falls_back_without_font_face():
    html = render_deck_html(_ONE, [], tokens=_tokens_with_fonts(heading="No Such Face, Arial, sans-serif", heading_dark=None,
                                                                 body="Helvetica Neue, Arial", mono=None))
    assert "@font-face" not in html and "No Such Face, Arial, sans-serif" in html


def test_dark_mode_uses_dark_ground_lime_accent_and_dark_heading_font():
    from arp.reporting.house_style import load_tokens

    t = load_tokens()
    light, dark = render_deck_html(_ONE, []), render_deck_html(_ONE, [], mode="dark")
    assert f"--bg: {t.color.background};" in light and f"--accent: {t.color.accent};" in light
    assert f"--bg: {t.color_dark.background};" in dark and "--accent: #c6ff3d;" in dark
    assert "font-family: 'Hanken Grotesk'" in dark and "font-family: 'Hanken Grotesk'" not in light


def test_chart_svg_uses_dark_ink_and_projector_sized_text():
    import re

    from arp.reporting.chart_builder import render_chart_svg
    from arp.reporting.house_style import load_tokens
    from arp.reporting.html_render import theme_from_tokens
    from tests.fixtures.stress_deck import stress_deck

    deck, ds = stress_deck("min")
    spec = next(s.chart for s in deck.slides if s.chart)
    svg = render_chart_svg(spec, ds, width_px=1200, height_px=600, theme=theme_from_tokens(load_tokens(), "dark"))
    assert f"fill: {load_tokens().color_dark.ink_muted.lower()}" in svg
    scale = 1200 / float(re.search(r'width="([\d.]+)pt"', svg).group(1))
    assert min(float(x) for x in re.findall(r"font-size: ([\d.]+)px", svg)) * scale >= 24
