"""Design checks: underfill, small text, low contrast, emphasis count (spec 2026-11-15-slide-components)."""

from arp.reporting.design_checks import check_slides, design_checks
from arp.reporting.house_style import load_tokens
from arp.reporting.render_model import Rect, Text
from arp.schemas.reporting import Deck, SlideContent
from arp.schemas.visuals import Points

TOKENS = load_tokens()


def _text(name, size=24, color="#121722", fill_under=None, y=400, text="x", **kw):
    return Text(name, 96, y, 400, 40, text, size, 400, "Inter", color, fill_under=fill_under, **kw)


def _slide(*body):
    return [_text("title", 56, y=104), *body]


def _rules(slides):
    return [(f.slide, f.rule, f.slot) for f in check_slides(slides, TOKENS)]


def test_ac11_underfill():
    short = _slide(Rect("a", 96, 400, 400, 200, "#f4f6f9"))
    full = _slide(Rect("a", 96, 400, 400, 296, "#f4f6f9"))
    assert _rules([short]) == [(0, "underfill", None)]
    assert _rules([full]) == []


def test_ac14_emphasis_count():
    body = [Rect("a", 96, 330, 400, 300, "#fff", emphasis=True), Rect("b", 600, 330, 400, 300, "#fff", emphasis=True)]
    assert _rules([_slide(*body)]) == [(0, "emphasis_count", None)]
    assert _rules([_slide(body[0], Rect("b", 600, 330, 400, 300, "#fff"))]) == []


def test_ac25_small_text():
    ground = Rect("a", 96, 330, 400, 300, "#fff")
    assert _rules([_slide(ground, _text("tiny", 17))]) == [(0, "small_text", "tiny")]
    assert _rules([_slide(ground, _text("ok", 18))]) == []


def test_ac26_low_contrast():
    ground = Rect("a", 96, 330, 400, 300, "#fff")
    assert _rules([_slide(ground, _text("pale", color="#aab4c3", fill_under="#ffffff"))]) == [(0, "low_contrast", "pale")]
    assert _rules([_slide(ground, _text("big", 48, color="#7a8494", fill_under="#ffffff"))]) == []
    assert _rules([_slide(ground, _text("mid", 47, color="#7a8494", fill_under="#ffffff"))]) == [(0, "low_contrast", "mid")]
    assert _rules([_slide(ground, _text("o", color="#aab4c3", fill_under="#ffffff", outline=True))]) == []
    assert _rules([_slide(ground, _text("e", 8, color="#aab4c3", fill_under="#ffffff", text=""))]) == []


def test_design_checks_renders_deck():
    deck = Deck(title="D", slides=[SlideContent(headline="H", kicker="K", visual=Points(points=["A", "B", "C"])),
                                   SlideContent(headline="No visual", kicker="K")])
    assert design_checks(deck, []) == []
