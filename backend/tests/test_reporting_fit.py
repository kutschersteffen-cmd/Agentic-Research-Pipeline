import pytest

from arp.reporting.browser import measure
from arp.reporting.fit import fit_deck
from arp.reporting.html_render import render_deck_html
from arp.reporting.slide_fill import SlotRewrite
from arp.schemas.reporting import Deck, ReportRequest, SlideContent

_REQ = ReportRequest(title="T", qualitative_notes="")


def _deck(slide):
    title = SlideContent(headline="T", layout="title", variant="plain", slots={"title": "T", "subtitle": "S"})
    return Deck(title="T", slides=[title, slide])


def _bullets(variant, items, notes=""):
    return SlideContent(headline="Headline", layout="bullets", variant=variant, slots={"items": items}, speaker_notes=notes)


def _sentence(n):
    return " ".join(f"word{k}" for k in range(n))


async def _overflow_ratio(slide):
    found = await measure(render_deck_html(_deck(slide), [], mode=_REQ.layout.theme))
    return [f for f in found if f.rule == "overflow" and f.slot == "items"]


@pytest.mark.asyncio
async def test_fit_shortens_mild_overflow(fake_llm):
    # Grow the text until the slot overflows mildly (ratio <= 1.6), then script a short rewrite.
    for n in range(100, 300, 10):
        slide = SlideContent(headline="Headline", layout="two_column", variant="text_text", slots={"left": _sentence(n), "right": "ok"})
        found = [f for f in await measure(render_deck_html(_deck(slide), [], mode="light")) if f.rule == "overflow"]
        if found:
            break
    assert found and float(found[0].message.removeprefix("ratio=")) <= 1.6
    llm = fake_llm({"SlotRewrite": [SlotRewrite(text="short")]})
    deck, findings = await fit_deck(_deck(slide), _REQ, llm)
    assert llm.calls == ["SlotRewrite"]
    assert deck.slides[1].slots["left"] == "short"
    assert findings == []


@pytest.mark.asyncio
async def test_fit_switches_to_roomier_variant(fake_llm):
    slide = _bullets("three", [_sentence(70)] * 5)
    llm = fake_llm({})
    deck, _ = await fit_deck(_deck(slide), _REQ, llm, max_passes=1)
    assert deck.slides[1].variant == "five" and llm.calls == []


@pytest.mark.asyncio
async def test_fit_splits_long_list(fake_llm):
    slide = _bullets("five", [_sentence(60)] * 10)
    deck, _ = await fit_deck(_deck(slide), _REQ, fake_llm({}))
    halves = deck.slides[1:]
    assert len(halves) >= 2 and {s.headline for s in halves} == {"Headline"}
    assert all("[split_from slide 1]" in s.speaker_notes for s in halves)


@pytest.mark.asyncio
async def test_fit_gives_up_after_three_passes(fake_llm):
    slide = _bullets("five", [_sentence(30)] * 40)
    deck, findings = await fit_deck(_deck(slide), _REQ, fake_llm({}))
    assert len(deck.slides) - 1 <= 8  # content slides
    assert "overflow" in {f.rule for f in findings}


@pytest.mark.asyncio
async def test_fit_reports_dropped_slot_on_variant_switch(fake_llm):
    slide = SlideContent(headline="Headline", layout="bullets", variant="three", slots={"items": [_sentence(70)] * 5, "extra": "x"})
    deck, findings = await fit_deck(_deck(slide), _REQ, fake_llm({}), max_passes=1)
    assert deck.slides[1].variant == "five"
    assert any(f.rule == "slot_dropped" and f.slot == "extra" for f in findings)
