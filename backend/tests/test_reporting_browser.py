import pytest
from pypdf import PdfReader

from arp.reporting.browser import BrowserUnavailable, measure, write_pdf, write_pngs
from arp.reporting.house_style import get_variant
from arp.reporting.html_render import render_deck_html
from arp.schemas.reporting import ColumnKind, DatasetColumn, Deck, QuantitativeDataset, SlideContent, TableSpec
from tests.fixtures.stress_deck import stress_deck


async def test_overlong_text_reports_overflow_with_ratio():
    deck = Deck(title="T", slides=[SlideContent(headline="h", layout="bullets", variant="three",
                                                slots={"items": ["word " * 600]})])
    [f] = [f for f in await measure(render_deck_html(deck, [])) if f.stage == "fit"]
    assert (f.rule, f.slot, f.slide) == ("overflow", "items", 0) and float(f.message.split("=")[1]) > 1.5


async def test_unbreakable_token_reports_overflow_x():
    deck = Deck(title="T", slides=[SlideContent(headline="h", layout="quote", variant="default",
                                                slots={"quote": "https://" + "x" * 300, "attribution": "a"})])
    assert {f.rule for f in await measure(render_deck_html(deck, [])) if f.stage == "fit"} == {"overflow_x"}


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


@pytest.mark.parametrize("mode", ["light", "dark"])
async def test_three_line_headline_overflows_the_two_line_box(mode):
    words = ["Transition", "plans", "you", "can", "check", "indicator", "by", "indicator"] * 6
    for n in range(8, 40):  # the first headline that wraps to exactly 3 lines
        deck = Deck(title="T", slides=[SlideContent(headline=" ".join(words[:n]), layout="bullets", variant="three", slots={"items": ["a"]})])
        html = render_deck_html(deck, [], mode=mode)
        lines = await _computed(html, "(() => { const h = document.querySelector('h1'); return Math.round(h.scrollHeight / parseFloat(getComputedStyle(h).lineHeight)); })()")
        if lines >= 3:
            break
    assert lines == 3
    assert [(f.rule, f.slot) for f in await measure(html) if f.stage == "fit"] == [("overflow", "headline")]


async def test_overlong_headline_reports_overflow():
    deck = Deck(title="T", slides=[SlideContent(headline="word " * 60, layout="bullets", variant="three", slots={"items": ["a"]})])
    [f] = [f for f in await measure(render_deck_html(deck, [])) if f.stage == "fit"]
    assert (f.rule, f.slot, f.slide) == ("overflow", "headline", 0)


@pytest.mark.parametrize("density", ["present", "committee"])
@pytest.mark.parametrize("fill", ["max", "short"])
@pytest.mark.parametrize("mode", ["light", "dark"])
async def test_stress_deck_max_fits_in_both_modes(mode, fill, density):
    deck, ds = stress_deck(fill, density)
    html = render_deck_html(deck, ds, mode=mode, density=density)
    assert "data:font/" in html
    # Every slot at its limit (or one word) is sparse or dense by construction; every other rule must hold at any fill.
    assert [f for f in await measure(html) if f.rule not in ("sparse", "dense")] == []


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
    assert [f for f in await measure(html) if f.stage == "fit"] == []


def test_card_items_split_title_and_body():
    deck = Deck(title="T", slides=[SlideContent(headline="h", layout="cards", variant="three",
                                                slots={"items": ["Grid: 64 rows: per company", "Plain item"]})])
    html = render_deck_html(deck, [])
    assert "<li><strong>Grid</strong><span>64 rows: per company</span></li>" in html and "<li><span>Plain item</span></li>" in html


@pytest.mark.parametrize("density", ["present", "committee"])
async def test_cards_are_content_sized_and_top_aligned(density):
    deck = Deck(title="T", slides=[SlideContent(headline="h", layout="cards", variant="three",
                                                slots={"items": ["Grid: one line of body text", "Score: another line", "Flags: a third"]})])
    got = await _computed(render_deck_html(deck, [], density=density), """[...document.querySelectorAll('[data-slot=items] li')].map(li => {
        const r = li.getBoundingClientRect(), slot = li.closest('.slot').getBoundingClientRect();
        return [li.querySelector('strong').getBoundingClientRect().top - r.top, r.bottom - li.querySelector('span').getBoundingClientRect().bottom, r.top - slot.top]; })""")
    assert all(title < 140 and foot < 40 and top == 0 for title, foot, top in got)  # number, title, body stacked tight from the slot top


async def test_eyebrow_renders_above_the_headline():
    deck = Deck(title="T", slides=[SlideContent(headline="Headline", eyebrow="Method", layout="cards", variant="three", slots={"items": ["a"]})])
    html = render_deck_html(deck, [])
    eb, h1 = await _computed(html, "['.eyebrow', 'h1'].map(q => document.querySelector(q).getBoundingClientRect()).map(r => [r.top, r.bottom])")
    assert eb[1] <= h1[0] and ">Method<" in html
    assert [f for f in await measure(html) if f.stage == "fit"] == []


@pytest.mark.parametrize("mode", ["light", "dark"])
async def test_takeaway_bar_is_a_tinted_box_with_a_bold_label(mode):
    deck = Deck(title="T", slides=[SlideContent(headline="h", layout="flow", variant="default",
                                                slots={"items": ["A :: a", "B :: b"], "takeaway_bar": "Engagement ask: restore a target"})])
    html = render_deck_html(deck, [], mode=mode)
    bar_bg, page_bg, label = await _computed(html, """[getComputedStyle(document.querySelector('[data-slot=takeaway_bar] .bar')).backgroundColor,
        getComputedStyle(document.querySelector('section')).backgroundColor,
        document.querySelector('[data-slot=takeaway_bar] .bar strong').textContent]""")
    assert bar_bg != page_bg and label == "Engagement ask:"


def test_density_is_on_the_body_and_committee_never_steps_up():
    deck = Deck(title="T", slides=[SlideContent(headline="h", layout="split", variant="list",
                                                slots={"statement": "Short claim.", "items": ["a", "b"]})])
    assert '<body data-density="committee">' in render_deck_html(deck, [])
    committee, present = render_deck_html(deck, [], density="committee"), render_deck_html(deck, [], density="present")
    assert 'data-slot="statement" data-role="body"' in committee and 'data-slot="statement" data-role="headline"' in present


def test_heat_cells_get_status_from_thresholds():
    ds = QuantitativeDataset(dataset_id="d", name="D", columns=[DatasetColumn(name="k", kind=ColumnKind.CATEGORY), DatasetColumn(name="v")],
                             rows=[{"k": "a", "v": "40%"}, {"k": "b", "v": 55}, {"k": "c", "v": 80}, {"k": "d", "v": "n/a"}])
    deck = Deck(title="T", slides=[SlideContent(headline="h", layout="table", variant="heat",
                                                table=TableSpec(dataset_id="d", heat={"v": [50, 70]}))])
    html = render_deck_html(deck, [ds])
    assert [s for s in ("low", "mid", "high") if f'data-status="{s}"' in html] == ["low", "mid", "high"]
    assert html.count("<td data-status=") == 3  # the category column and the non-number are not tinted
    for k in ("high", "mid", "low", "neutral"):
        assert f"--status-{k}:" in html


async def test_malformed_structured_slot_renders_as_a_list_and_reports_a_data_finding():
    quads = [f"Q{i} :: sub :: text :: high" for i in range(4)][:2]  # the reviewer's case: half a 2x2
    deck = Deck(title="T", slides=[SlideContent(headline="h", layout="matrix2x2", variant="default", slots={"quadrants": quads})])
    html = render_deck_html(deck, [])
    assert "<li>Q0 :: sub :: text :: high</li>" in html
    [f] = [f for f in await measure(html) if f.stage != "design"]
    assert (f.stage, f.rule, f.slot, f.slide) == ("data", "bad_structure", "quadrants", 0) and "exactly 4" in f.message


# ---- measured design check (spec §3) ----


def _design(found, rule=None):
    return [f for f in found if f.stage == "design" and f.severity == "warn" and rule in (None, f.rule)]


def _styled(html: str, css: str) -> str:
    return html.replace("</head>", f"<style>{css}</style></head>")


_TITLE = SlideContent(headline="T", layout="title", variant="plain", slots={"title": "T", "subtitle": "S"})
_FOUR = ["Code checks every quote", "A second model rechecks", "Analysts review the rest"]


@pytest.mark.parametrize("density", ["present", "committee"])
@pytest.mark.parametrize("mode", ["light", "dark"])
async def test_sparse_slide_flagged(mode, density):
    deck = Deck(title="T", slides=[_TITLE, SlideContent(headline="h", layout="bullets", variant="three", slots={"items": _FOUR})])
    [f] = _design(await measure(render_deck_html(deck, [], mode=mode, density=density)), "sparse")
    assert f.slide == 1 and f.message.endswith(f"< {0.55 if density == 'present' else 0.70:.2f}")


@pytest.mark.parametrize("mode", ["light", "dark"])
async def test_committee_short_heat_table_with_a_takeaway_bar_is_sparse(mode):
    """The bar sits in the footer band, so it does not stretch the measured span."""
    ds = QuantitativeDataset(dataset_id="d", name="D", columns=[DatasetColumn(name="k", kind=ColumnKind.CATEGORY), DatasetColumn(name="v")],
                             rows=[{"k": "a", "v": 40}, {"k": "b", "v": 80}])
    deck = Deck(title="T", slides=[_TITLE, SlideContent(headline="h", layout="table", variant="heat", table=TableSpec(dataset_id="d", heat={"v": [50, 70]}),
                                                        slots={"commentary": "Two rows.", "takeaway_bar": "So what: little here"})])
    [f] = _design(await measure(render_deck_html(deck, [ds], mode=mode, density="committee")), "sparse")
    assert f.slide == 1


@pytest.mark.parametrize("mode", ["light", "dark"])
async def test_title_and_section_not_sparse(mode):
    deck = Deck(title="T", slides=[_TITLE, SlideContent(headline="h", layout="section", variant="default", slots={"number": "1", "title": "Part"})])
    assert _design(await measure(render_deck_html(deck, [], mode=mode))) == []


@pytest.mark.parametrize("mode", ["light", "dark"])
async def test_small_text_flagged(mode):
    deck = Deck(title="T", slides=[_TITLE, SlideContent(headline="h", layout="summary", variant="default", slots={"items": _FOUR})])
    html = _styled(render_deck_html(deck, [], mode=mode), "[data-slot=items] { font-size: 18px !important; }")
    [f] = _design(await measure(html), "small_text")
    assert (f.slide, f.slot) == (1, "items") and "18" in f.message


@pytest.mark.parametrize("mode", ["light", "dark"])
async def test_footer_chrome_ignored(mode):
    deck, ds = stress_deck("min")
    deck.slides[1].source_refs = ["A source line in the footer"]
    html = render_deck_html(deck, ds, mode=mode)
    assert "<footer data-chrome>" in html
    assert _design(await measure(html), "small_text") == []


async def test_no_focal_flagged():
    deck = Deck(title="T", slides=[_TITLE, SlideContent(headline="h", layout="summary", variant="default", slots={"items": _FOUR})])
    html = _styled(render_deck_html(deck, []), "h1.t-headline, [data-slot=items] { font-size: 28px !important; }")
    [f] = _design(await measure(html), "no_focal")
    assert f.slide == 1


async def test_unbalanced_uses_the_rendered_anchor():
    deck = Deck(title="T", slides=[_TITLE, SlideContent(headline="h", layout="statement", variant="plain", slots={"statement": "Talk outruns walk."})])
    html = render_deck_html(deck, [], density="present")
    assert 'data-anchor="middle"' in html and _design(await measure(html), "unbalanced") == []
    [f] = _design(await measure(_styled(html, "[data-slot=statement] { justify-content: flex-start !important; }")), "unbalanced")
    assert f.slide == 1
    cards = Deck(title="T", slides=[_TITLE, SlideContent(headline="h", layout="cards", variant="three", slots={"items": _FOUR})])
    for density in ("present", "committee"):  # deck.css top-aligns cards at either density
        assert 'data-anchor="top"' in render_deck_html(cards, [], density=density)


async def test_crowded_flagged():
    deck = Deck(title="T", slides=[_TITLE, SlideContent(headline="h", layout="compare", variant="default", slots={"left": "First pass.", "right": "Second pass."})])
    html = _styled(render_deck_html(deck, []), "[data-slot=right] { left: 96px !important; top: 340px !important; height: 100px !important; }")
    assert [f.slide for f in _design(await measure(html), "crowded")] == [1]


async def test_dense_counts_headline_and_slots_per_density():
    words = ["one two three four five six seven eight nine ten eleven twelve thirteen"] * 4  # 52 words + the headline
    deck = Deck(title="T", slides=[_TITLE, SlideContent(headline="Ten words in this headline make the slide dense now", eyebrow="Not counted at all",
                                                        layout="summary", variant="default", slots={"items": words})])
    [f] = _design(await measure(render_deck_html(deck, [], density="present")), "dense")
    assert f.slide == 1 and f.message.startswith("62 words")
    assert _design(await measure(render_deck_html(deck, [], density="committee")), "dense") == []


def _tpa(fixture):
    from arp.reporting.art_direct import direct

    req, story, fills = fixture()
    for s, h in zip(fills, story.slides, strict=True):
        s.headline = h.headline
    title = SlideContent(headline=story.title, layout="title", variant="plain", slots={"title": story.title, "subtitle": story.subtitle})
    return req, direct(Deck(title=story.title, slides=[title, *fills]), req.layout.density)[0]


@pytest.mark.parametrize("fixture", ["tpa_pitch", "tpa_pitch_committee"])
@pytest.mark.parametrize("mode", ["light", "dark"])
async def test_tpa_v2_layouts_have_no_design_findings(mode, fixture, fake_llm):
    """The pipeline path: art direction, measure, then the one design retry."""
    import importlib

    from arp.reporting.house_pipeline import design_retry

    req, deck = _tpa(getattr(importlib.import_module(f"tests.fixtures.{fixture}"), fixture))
    req = req.model_copy(update={"layout": req.layout.model_copy(update={"theme": mode})})
    found = await measure(render_deck_html(deck, req.datasets, mode=mode, density=req.layout.density))
    deck, findings = await design_retry(deck, req, fake_llm({}), found)  # no LLM call: nothing overflows
    assert [f for f in findings if f.severity == "warn"] == [], [(f.slide, f.rule, f.slot, f.message) for f in findings]
    # The rhythm binds the final deck: no layout three times running, a visual slide in every three content slides.
    content = [s for s in deck.slides[1:] if s.layout != "section"]
    assert all(len({s.layout for s in deck.slides[i : i + 3]}) > 1 for i in range(len(deck.slides) - 2)), [s.layout for s in deck.slides]
    assert all(any(get_variant(s.layout, s.variant).visual for s in content[i : i + 3]) for i in range(len(content) - 2)), \
        [(s.layout, s.variant) for s in content]


@pytest.mark.parametrize("density", ["present", "committee"])
async def test_thin_cards_are_sparse_then_pass_after_one_retry(density, fake_llm):
    from arp.reporting.house_pipeline import design_retry
    from arp.schemas.reporting import LayoutInstructions, ReportRequest

    req = ReportRequest(title="T", qualitative_notes="", layout=LayoutInstructions(density=density))
    deck = Deck(title="T", slides=[_TITLE, SlideContent(headline="h", layout="cards", variant="three", slots={"items": _FOUR})])
    found = await measure(render_deck_html(deck, [], density=density))
    assert [(f.slide, f.rule) for f in _design(found)] == [(1, "sparse")]
    deck, findings = await design_retry(deck, req, fake_llm({}), found)
    assert [(f.rule, f.severity, f.message) for f in findings if f.stage == "design"] == [
        ("relayout", "info", "cards/three → cards/rows (sparse)")]
