import pytest
from pypdf import PdfReader

from arp.reporting.browser import BrowserUnavailable, measure, write_pdf, write_pngs
from arp.reporting.html_render import render_deck_html
from arp.schemas.reporting import ColumnKind, DatasetColumn, Deck, QuantitativeDataset, SlideContent, TableSpec
from tests.fixtures.stress_deck import stress_deck


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


@pytest.mark.parametrize("fill", ["max", "short"])
@pytest.mark.parametrize("mode", ["light", "dark"])
async def test_stress_deck_max_fits_in_both_modes(mode, fill):
    deck, ds = stress_deck(fill)
    html = render_deck_html(deck, ds, mode=mode)
    assert "data:font/" in html
    assert await measure(html) == []


@pytest.mark.parametrize("mode", ["light", "dark"])
async def test_big_numbers_are_ink_and_labels_and_table_headers_mono(mode):
    from playwright.async_api import async_playwright

    from arp.reporting.house_style import load_tokens

    ds = QuantitativeDataset(dataset_id="d", name="D", columns=[DatasetColumn(name="k", kind=ColumnKind.CATEGORY)], rows=[{"k": "r"}])
    deck = Deck(title="T", slides=[
        SlideContent(headline="h", layout="big_number", variant="three", slots={**{f"number_{i}": f"{i}%" for i in (1, 2, 3)}, "label_1": "a"}),
        SlideContent(headline="h", layout="table", variant="compact", table=TableSpec(dataset_id="d")),
    ])
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(render_deck_html(deck, [ds], mode=mode))
        colours = await page.evaluate("[...document.querySelectorAll('.k-number')].map(e => getComputedStyle(e).color)")
        mono = await page.evaluate("""['[data-slot=label_1]', '.slot th'].map(q => {
            const s = getComputedStyle(document.querySelector(q)); return [s.fontFamily, s.textTransform]; })""")
        await browser.close()
    ink = load_tokens().colors(mode).ink.lstrip("#")
    rgb = f"rgb({int(ink[:2], 16)}, {int(ink[2:4], 16)}, {int(ink[4:], 16)})"
    assert colours == [rgb] * 3
    assert mono[0][0].startswith('"Geist Mono"') and mono[1] == [mono[0][0], "uppercase"]


async def _computed(html: str, js: str):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        await page.set_content(html)
        await page.evaluate("document.fonts.ready")
        out = await page.evaluate(js)
        await browser.close()
    return out


@pytest.mark.parametrize("mode", ["light", "dark"])
async def test_table_text_at_least_24px(mode):
    deck, ds = stress_deck("max")
    deck.slides = [s for s in deck.slides if (s.layout, s.variant) == ("table", "compact")]
    html = render_deck_html(deck, ds, mode=mode)
    sizes = await _computed(html, "[...document.querySelectorAll('.slot th, .slot td')].map(e => parseFloat(getComputedStyle(e).fontSize))")
    assert sizes and min(sizes) >= 24


@pytest.mark.parametrize("mode", ["light", "dark"])
async def test_cards_with_uneven_items_keep_equal_heights(mode):
    items = ["Three word item", "Eight words: " + "dolore " * 6, "Twelve words in this one: " + "dolore " * 7]
    deck = Deck(title="T", slides=[SlideContent(headline="h", layout="cards", variant="three", slots={"items": items})])
    html = render_deck_html(deck, [], mode=mode)
    heights = await _computed(html, "[...document.querySelectorAll('[data-slot=items] li')].map(e => e.getBoundingClientRect().height)")
    assert len(heights) == 3 and max(heights) - min(heights) <= 1
    assert await measure(html) == []


def test_card_items_split_title_and_body():
    deck = Deck(title="T", slides=[SlideContent(headline="h", layout="cards", variant="three",
                                                slots={"items": ["Grid: 64 rows: per company", "Plain title"]})])
    html = render_deck_html(deck, [])
    assert "<strong>Grid</strong><span>64 rows: per company</span>" in html and "<strong>Plain title</strong>" in html
