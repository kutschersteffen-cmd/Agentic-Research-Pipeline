"""The `flow` renderer, legend, both writers, notes and design checks (spec house-deck-flowchart-slides, slice 3)."""

import pytest
from pptx import Presentation

from arp.reporting.browser import _page
from arp.reporting.design_checks import design_checks
from arp.reporting.flow_layout import layout_flows
from arp.reporting.house_pptx import build_house_pptx
from arp.reporting.house_style import load_tokens
from arp.reporting.html_render import render_deck_html
from arp.reporting.render_model import Line, Rect, Text, VisualDataError, render_slide
from arp.schemas.reporting import Deck, SlideContent
from arp.schemas.visuals import Flow
from tests.test_flow_layout import F1, F2, F3, F4

TOKENS = load_tokens()


def _deck(*texts: str) -> Deck:
    return Deck(title="Flows", slides=[SlideContent(headline=f"Flow F{k}", visual=Flow(mermaid=m)) for k, m in enumerate(texts, 1)])


@pytest.fixture(scope="module")
async def fdeck():
    deck, _ = await layout_flows(_deck(F1, F2, F3, F4), TOKENS)
    return deck


def _prims(deck: Deck, mode="light", index=0) -> dict:
    return {p.name: p for p in render_slide(deck.slides[index], index, deck, TOKENS, {}, mode)}


async def test_html_and_pptx_boxes_match(fdeck, tmp_path):
    prs = Presentation(str(build_house_pptx(fdeck, [], tmp_path / "f.pptx")))
    async with _page(render_deck_html(fdeck, [])) as page:
        html = await page.evaluate("""() => [...document.querySelectorAll('section.slide')].map(s => Object.fromEntries(
            [...s.querySelectorAll('[data-name]')].map(el => { const r = el.getBoundingClientRect(), b = s.getBoundingClientRect();
                return [el.dataset.name, [r.left - b.left, r.top - b.top, r.width, r.height]]; })))""")
    for i, slide in enumerate(prs.slides):
        pptx = {sh.name: (sh.left / 9525, sh.top / 9525, sh.width / 9525, sh.height / 9525) for sh in slide.shapes}
        assert set(html[i]) == set(pptx), i
        assert {"step:q2", "step:q2:label", "step:q2:tag", "arrow:2:label", "legend:stored"} <= set(html[0])
        for name, box in html[i].items():
            assert box == pytest.approx(list(pptx[name]), abs=1), (i, name)


async def test_outlines_and_emphasis(fdeck):
    p = _prims(fdeck)
    plan = p["step:plan"]
    assert (plan.line, plan.line_w, plan.emphasis) == ("#2a78d6", 4, True)
    assert [n for n, x in p.items() if getattr(x, "emphasis", False)] == ["step:plan"]
    assert (p["step:log"].line, p["step:log"].line_w) == ("#4f5a6b", 2)
    assert (p["step:q2"].line, p["step:q2"].line_w) == ("#121722", 2)


async def test_decision_outline_is_4px_when_not_emphasised(fdeck):
    flow = fdeck.slides[0].visual.model_copy(update={"emphasis": None})
    deck = fdeck.model_copy(update={"slides": [fdeck.slides[0].model_copy(update={"visual": flow})]})
    assert (_prims(deck)["step:plan"].line, _prims(deck)["step:plan"].line_w) == ("#121722", 4)


async def test_actor_fills_and_stored_band(fdeck):
    p = _prims(fdeck)
    assert {s: p[f"step:{s}"].fill for s in ("q2", "screen", "add")} == dict.fromkeys(("q2", "screen", "add"), "#ffffff")
    assert {s: p[f"step:{s}"].fill for s in ("engage", "plan", "log")} == dict.fromkeys(("engage", "plan", "log"), "#c4ccd7")
    band, log = p["step:log:stored"], p["step:log"]
    assert (band.fill, band.h) == ("#121722", 8)
    assert band.y + band.h == pytest.approx(log.y + log.h, abs=1)
    assert "step:q2:stored" not in p


async def test_legend(fdeck):
    p = _prims(fdeck)
    assert (p["legend:1:text"].text, p["legend:2:text"].text, p["legend:stored:text"].text) == ("TEAM", "STEWARD", "STORED RESULT")
    assert (p["legend:1"].fill, p["legend:2"].fill) == ("#ffffff", "#c4ccd7")
    swatches = [p[n] for n in ("legend:1", "legend:2", "legend:stored")]
    assert all(s.y + s.h == pytest.approx(920, abs=1) for s in swatches)
    assert swatches[0].x == 96
    assert p["legend:1:text"].x == swatches[0].x + 24 + 12
    assert swatches[1].x == p["legend:1:text"].x + p["legend:1:text"].w + 32
    assert not any(n.startswith("legend:") for n in _prims(fdeck, index=2)), "F3 has no actors and nothing stored"


@pytest.mark.parametrize("mode", ["light", "dark"])
async def test_text_sizes(fdeck, mode):
    p = _prims(fdeck, mode)
    labels = [x for n, x in p.items() if n.startswith("step:") and n.endswith(":label")]
    assert len(labels) == 6 and all((x.size, x.weight) == (28, 600) and x.text.count("\n") <= 1 for x in labels)
    small = [x for n, x in p.items() if n.endswith(":tag") or (n.startswith("arrow:") and n.endswith(":label"))]
    assert len(small) == 4 and all(x.size == 20 for x in small)
    assert p["step:q2:tag"].text == "ESEF filings"


async def test_arrows_follow_the_layout(fdeck):
    p, lay = _prims(fdeck), fdeck.slides[0].visual.layout
    arrows = [p[f"arrow:{n}"] for n in range(1, 6)]
    assert all(isinstance(a, Line) and a.arrow and a.width == 2 and a.color == "#121722" for a in arrows)
    assert [a.points for a in arrows] == [list(a.points) for a in lay.arrows]
    assert [p[f"arrow:{n}:label"].text for n in (2, 4, 5)] == ["over 5.5x", "yes", "no"]
    assert "arrow:1:label" not in p
    assert p["arrow:2:label"].fill_under == "#ffffff"


@pytest.mark.parametrize("mode", ["light", "dark"])
async def test_design_checks_pass(fdeck, mode):
    deck, _ = await layout_flows(_deck(F1, F2, F3), TOKENS, mode)
    rules = {"small_text", "low_contrast", "underfill", "emphasis_count"}
    assert [f for f in design_checks(deck, [], TOKENS, mode) if f.rule in rules] == []


async def test_dark_mode_uses_only_graphite_dark(fdeck):
    dark = set(TOKENS.graphite_dark.values())
    for name, p in _prims(fdeck, "dark").items():
        if name.startswith(("step:", "arrow:", "legend:")):
            colours = [getattr(p, k) for k in ("fill", "line", "color", "fill_under") if getattr(p, k, None)]
            assert set(colours) <= dark, name


def test_flow_without_layout_raises():
    deck = _deck(F1)
    with pytest.raises(VisualDataError, match="^flow has no layout$"):
        render_slide(deck.slides[0], 0, deck, TOKENS, {})


async def test_pptx_notes_end_with_the_mermaid_source(fdeck, tmp_path):
    deck = fdeck.model_copy(update={"slides": [fdeck.slides[0].model_copy(update={"speaker_notes": "Walk through it."})]})
    prs = Presentation(str(build_house_pptx(deck, [], tmp_path / "f.pptx")))
    notes = prs.slides[0].notes_slide.notes_text_frame.text
    assert notes == "Walk through it.\nMermaid source:\n" + F1.rstrip()


async def test_only_primitive_kinds_the_writers_know(fdeck):
    assert all(isinstance(p, Rect | Text | Line) for p in render_slide(fdeck.slides[3], 3, fdeck, TOKENS, {}))
