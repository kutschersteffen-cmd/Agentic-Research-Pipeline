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
