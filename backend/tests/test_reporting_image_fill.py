"""House-deck image slides: the model calls -- storyline offer, fill with previews, name checks, fallback, lint
(spec house-deck-image-slides, slice 4)."""

import io

import pytest
from PIL import Image

from arp.reporting.fit import _field
from arp.reporting.lint import lint_deck
from arp.reporting.slide_fill import fill_slide
from arp.reporting.storyline import draft_storyline
from arp.schemas.reporting import Deck, ReportRequest, SlideContent, Storyline, StorylineSlide
from arp.schemas.visuals import ImageItem, ImageVisual
from arp.storage.reporting_store import ReportingStore
from tests.test_reporting_image_hero import FILES

_STORY = StorylineSlide(headline="The landing page leads with the answer.", purpose="p", visual="image")


@pytest.fixture
def setup(tmp_path):
    store = ReportingStore(tmp_path / "reports", tmp_path / "tpl")
    a = store.save_report_image("rpt_a", "a", FILES["quad"](), alt="Landing page")
    b = store.save_report_image("rpt_a", "b", FILES["tall"]())
    request = ReportRequest(title="T", qualitative_notes="n", images=[a, b])
    return request, store.load_report_images("rpt_a", request)


def _slide(*images: ImageItem, variant="hero") -> SlideContent:
    return SlideContent(headline="x", visual=ImageVisual(variant=variant, images=list(images)))


async def test_fill_shows_previews_in_registration_order(setup, fake_llm):  # AC-43
    request, images = setup
    llm = fake_llm({"SlideContent": [_slide(ImageItem(name="a"))]})
    slide, findings, _ = await fill_slide(_STORY, 1, request, llm, images=images)
    assert [Image.open(io.BytesIO(p)).size for p in llm.images[0]] == [(768, 384), (384, 768)]
    assert all(Image.open(io.BytesIO(p)).format == "PNG" for p in llm.images[0])
    assert slide.visual.variant == "hero" and slide.visual.images[0].name == "a" and findings == []
    assert "- a (2000×1000): Landing page\n- b (1000×2000):\n" in llm.prompts[0]


async def test_storyline_offers_image_and_lists_images(setup, fake_llm):  # AC-45
    request, _ = setup
    llm = fake_llm({"Storyline": [Storyline(title="T", slides=[])]})
    await draft_storyline(request, llm)
    assert "one of kpi_row, chart, comparison_table, two_column, points, image;" in llm.prompts[0]
    assert "- a (2000×1000): Landing page\n" in llm.prompts[0] and "- b (1000×2000):\n" in llm.prompts[0]


async def test_storyline_without_images_is_unchanged(fake_llm):  # AC-59
    llm = fake_llm({"Storyline": [Storyline(title="T", slides=[])]})
    await draft_storyline(ReportRequest(title="T", qualitative_notes="n"), llm)
    assert "one of kpi_row, chart, comparison_table, two_column, points;" in llm.prompts[0]
    assert "×" not in llm.prompts[0]


async def test_unknown_name_retries_then_falls_back(setup, fake_llm):  # AC-46
    request, images = setup
    llm = fake_llm({"SlideContent": [_slide(ImageItem(name="nope"))] * 2})
    slide, findings, _ = await fill_slide(_STORY, 1, request, llm, images=images)
    assert llm.calls == ["SlideContent", "SlideContent"] and slide.visual.type == "points"
    bad = [f for f in findings if f.rule == "bad_reference"]
    assert len(bad) == 1 and "unknown image 'nope'; registered: a, b" in bad[0].message


async def test_no_images_falls_back_without_a_call(fake_llm):  # AC-47
    llm = fake_llm({})
    slide, findings, _ = await fill_slide(_STORY, 1, ReportRequest(title="T", qualitative_notes="n"), llm)
    assert llm.calls == [] and slide.visual.type == "points"
    assert [f.message for f in findings if f.rule == "bad_reference"] == ["no images registered"]


async def test_duplicate_image_is_sent_back(setup, fake_llm):  # AC-48
    request, images = setup
    twice = {"headline": "x", "visual": {"type": "image", "variant": "gallery",
                                          "images": [{"name": "a", "caption": "One"}, {"name": "a", "caption": "Two"}]}}
    good = _slide(ImageItem(name="a", caption="One"), ImageItem(name="b", caption="Two"), variant="gallery")
    llm = fake_llm({"SlideContent": [twice, good]})
    slide, _, _ = await fill_slide(_STORY, 1, request, llm, images=images)
    assert "image 'a' appears twice" in llm.prompts[1] and slide.visual == good.visual


def _lint(*items: ImageItem, variant="hero") -> list:
    deck = Deck(title="T", slides=[SlideContent(headline="h"), _slide(*items, variant=variant)])
    return [f for f in lint_deck(deck, ReportRequest(title="T", qualitative_notes="no figures")) if f.slide == 1]


def test_lint_flags_unsourced_caption_number():  # AC-49
    found = _lint(ImageItem(name="a", caption="Up 47%"), ImageItem(name="b", caption="Flat"), variant="gallery")
    assert [f.rule for f in found] == ["number_not_in_source"] and "47%" in found[0].message


def test_lint_skips_image_names():  # AC-50
    assert _lint(ImageItem(name="q3-2025")) == []


def test_fit_maps_split_points_and_captions():
    assert _field("image", "points:row:2") == ("points", 1)
    assert _field("image", "image:3:caption") == ("images", 2, "caption")
