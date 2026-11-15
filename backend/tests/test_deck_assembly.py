"""Task 9: deck settings, the storyline prompt and deck assembly (spec rows AC-16, AC-17, AC-33)."""

import pytest

from arp.reporting.browser import measure
from arp.reporting.house_pipeline import build_house_deck
from arp.reporting.html_render import render_deck_html
from arp.reporting.html_writer import _text
from arp.reporting.render_model import Text
from arp.reporting.slide_fill import fill_slide
from arp.reporting.storyline import DESIGN_GUIDE, draft_storyline
from arp.reporting.visual_qa import QAResult
from arp.schemas.reporting import (
    Deck,
    DeckSettings,
    LayoutInstructions,
    OutputFormat,
    ReportRequest,
    SlideContent,
    Storyline,
    StorylineSlide,
)
from arp.schemas.visuals import Cover, NextAction, Points, SectionPlan
from arp.storage.reporting_store import ReportingStore

_HOUSE = LayoutInstructions(output_format=OutputFormat.HOUSE_DECK)


def _request(**kw) -> ReportRequest:
    return ReportRequest(title="T", qualitative_notes="n", layout=_HOUSE, **kw)


_CLOSING = [NextAction(text="Approve the plan"), NextAction(text="Brief the board"), NextAction(text="Start in May")]


def _store(tmp_path) -> ReportingStore:
    return ReportingStore(tmp_path / "reports", tmp_path / "templates")


def _points() -> SlideContent:
    return SlideContent(headline="x", visual=Points(points=["Alpha rose", "Beta fell", "Gamma held"]))


async def test_ac16_prompt(fake_llm):
    drafted = Storyline(title="T", slides=[StorylineSlide(headline="h", purpose="p", visual="kpi_row", rationale="Three numbers")],
                        closing=_CLOSING)
    llm = fake_llm({"Storyline": [drafted]})
    storyline, _ = await draft_storyline(_request(), llm)
    prompt = llm.prompts[0]
    for word in ("committee", "recommendation", "balanced", "kpi_row", "chart", "comparison_table", "two_column", "points"):
        assert word in prompt
    for pr2 in ("linear_flow", "swimlane_flow", "matrix_2x2", "timeline"):
        assert pr2 not in prompt
    assert DESIGN_GUIDE.strip() in prompt and len(DESIGN_GUIDE.strip().splitlines()) <= 12
    assert storyline.slides[0].visual == "kpi_row" and storyline.slides[0].rationale == "Three numbers"


async def test_storyline_rejects_long_subheading(fake_llm):
    long = Storyline(title="T", slides=[StorylineSlide(headline="h", purpose="p", subheading=" ".join(["w"] * 17))])
    with pytest.raises(ValueError, match="16 words"):
        await draft_storyline(_request(), fake_llm({"Storyline": [long, long]}))


async def test_storyline_rejects_short_closing(fake_llm):
    short = Storyline(title="T", slides=[StorylineSlide(headline="h", purpose="p", visual="points")], closing=_CLOSING[:1])
    with pytest.raises(ValueError, match="closing"):
        await draft_storyline(_request(), fake_llm({"Storyline": [short, short]}))


async def test_storyline_retries_once_with_errors(fake_llm):
    bad = Storyline(title=" ".join(["w"] * 11), slides=[StorylineSlide(headline="h", purpose="p", visual="points")])
    good = Storyline(title="T", slides=[StorylineSlide(headline="h", purpose="p", visual="points")], closing=_CLOSING)
    llm = fake_llm({"Storyline": [bad, good]})
    storyline, usage = await draft_storyline(_request(), llm)
    assert storyline.title == "T" and llm.calls == ["Storyline", "Storyline"]
    assert "10 words" in llm.prompts[1] and "closing" in llm.prompts[1] and usage.input_tokens == 20


async def test_fill_prompt_has_design_guide(fake_llm):
    llm = fake_llm({"SlideContent": [_points()]})
    await fill_slide(StorylineSlide(headline="H", purpose="p", visual="points"), 1, _request(), llm)
    assert DESIGN_GUIDE.strip() in llm.prompts[0]


async def test_ac17_order(tmp_path, fake_llm):
    slides = [StorylineSlide(headline=f"Claim {k} holds", purpose="p", visual="points", section=k % 2) for k in range(4)]
    storyline = Storyline(
        title="Deck", slides=slides,
        sections=[SectionPlan(title="Where we stand"), SectionPlan(title="What we do")],
        closing=_CLOSING,
    )
    llm = fake_llm({"SlideContent": [_points() for _ in range(4)], "QAResult": [QAResult(edits=[])]})
    deck, _ = await build_house_deck("r1", _request(), storyline, llm, _store(tmp_path))
    assert [s.visual.type for s in deck.slides] == ["cover", "section", "points", "points", "section", "points", "points", "next_steps"]
    assert [s.headline for s in deck.slides[2:4]] == ["Claim 0 holds", "Claim 2 holds"]
    assert [s.headline for s in deck.slides[5:7]] == ["Claim 1 holds", "Claim 3 holds"]
    assert deck.slides[1].visual.agenda == ["Where we stand", "What we do"] and deck.slides[4].visual.number == 2
    assert len(deck.slides[-1].visual.actions) == 3 and deck.slides[-1].kicker == "Next steps"


async def test_ac33_profile_cap(tmp_path, fake_llm):
    slides = [StorylineSlide(headline=f"Claim {k} holds", purpose="p", visual="points") for k in range(10)]
    llm = fake_llm({"SlideContent": [_points() for _ in range(8)], "QAResult": [QAResult(edits=[])]})
    request = _request(deck=DeckSettings(profile="executive"))
    deck, findings = await build_house_deck("r1", request, Storyline(title="Deck", slides=slides), llm, _store(tmp_path))
    assert [s.visual.type for s in deck.slides].count("points") == 8
    assert [f.rule for f in findings].count("profile_cap") == 1


async def test_storyline_rejects_long_title(fake_llm):
    long = Storyline(title=" ".join(["w"] * 11), slides=[StorylineSlide(headline="h", purpose="p")])
    with pytest.raises(ValueError, match="10 words"):
        await draft_storyline(_request(), fake_llm({"Storyline": [long, long]}))


async def test_large_one_line_title_does_not_overflow():
    # Geist's glyph box (1.3em) overhangs the 1.2 line height; at 72 px that read as an overflow on every cover.
    deck = Deck(title="Deck", slides=[SlideContent(headline="Deck", visual=Cover(title="Deck"))])
    assert await measure(render_deck_html(deck, [])) == []


async def test_partial_line_overflow_is_flagged():
    # Two 72 px lines (173 px) in a 150 px box: clipped by 23 px, less than a line but far more than glyph overhang.
    text = Text("cover:title", 0, 0, 400, 150, "Utilities lag again", 72, 600, "Geist", "#000000")
    html = f'<section data-visual="cover" data-slide="0" style="position:relative;width:1920px;height:1080px">{_text(text)}</section>'
    assert [f.slot for f in await measure(html) if f.rule == "overflow"] == ["cover:title"]
