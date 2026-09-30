from pathlib import Path

import pytest
from pypdf import PdfReader

from arp.reporting.browser import BrowserUnavailable, measure, write_pdf, write_pngs
from arp.reporting.house_style import Tokens
from arp.reporting.html_render import render_deck_html
from arp.schemas.reporting import Deck, SlideContent
from tests.fixtures.stress_deck import stress_deck


async def test_stress_deck_max_has_no_fit_findings():
    deck, ds = stress_deck("max")
    assert await measure(render_deck_html(deck, ds)) == []


async def test_overlong_text_reports_overflow_with_ratio():
    deck = Deck(title="T", slides=[SlideContent(headline="h", layout="bullets", variant="three",
                                                slots={"items": ["word " * 600]})])
    [f] = await measure(render_deck_html(deck, []))
    assert (f.rule, f.slot, f.slide) == ("overflow", "items", 0) and float(f.message.split("=")[1]) > 1.5


async def test_unbreakable_token_reports_overflow_x():
    deck = Deck(title="T", slides=[SlideContent(headline="h", layout="quote", variant="default",
                                                slots={"quote": "https://" + "x" * 300, "attribution": "a"})])
    assert {f.rule for f in await measure(render_deck_html(deck, []))} == {"overflow_x"}


async def test_pdf_has_one_page_per_slide(tmp_path):
    deck, ds = stress_deck("min")
    out = await write_pdf(render_deck_html(deck, ds), tmp_path / "d.pdf")
    assert len(PdfReader(out).pages) == len(deck.slides)


async def test_pngs_are_zero_padded_one_per_slide(tmp_path):
    deck, ds = stress_deck("min")
    paths = await write_pngs(render_deck_html(deck, ds), tmp_path)
    assert [p.name for p in paths] == [f"page-{i:03d}.png" for i in range(1, len(deck.slides) + 1)]


async def test_missing_chromium_raises_install_hint(monkeypatch):
    monkeypatch.setenv("ARP_CHROMIUM_PATH", "/nonexistent/chrome")
    with pytest.raises(BrowserUnavailable, match="playwright install chromium"):
        await measure("<html></html>")


async def test_overlong_headline_reports_overflow():
    deck = Deck(title="T", slides=[SlideContent(headline="word " * 60, layout="bullets", variant="three", slots={"items": ["a"]})])
    [f] = await measure(render_deck_html(deck, []))
    assert (f.rule, f.slot, f.slide) == ("overflow", "headline", 0)


_DIRECTIONS = sorted((Path(__file__).parents[1] / "arp/reporting/style/directions").glob("*.json"))


@pytest.mark.parametrize("path", _DIRECTIONS, ids=[p.stem for p in _DIRECTIONS])
async def test_stress_deck_max_fits_in_every_candidate_direction(path):
    deck, ds = stress_deck("max")
    html = render_deck_html(deck, ds, tokens=Tokens.model_validate_json(path.read_text()))
    assert "data:font/" in html
    assert await measure(html) == []
