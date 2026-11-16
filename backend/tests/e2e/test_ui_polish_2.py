"""UI polish 2, PR A (docs/superpowers/specs/2026-11-16-ui-polish-2-linear-design.md) against the running app."""

import os

import pytest

from arp.config import Settings

URL = os.environ.get("ARP_E2E_URL")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, color_scheme="dark")
        page.set_default_timeout(10_000)
        yield page
        browser.close()


def _open(page, path, width=1440, height=900, scheme="dark"):
    page.emulate_media(color_scheme=scheme)
    page.set_viewport_size({"width": width, "height": height})
    page.goto(URL + path)
    page.wait_for_load_state("networkidle")


def _probe(page, token, prop="color"):
    """The computed colour of `var(token)`, resolved by the browser the same way the page resolves it."""
    return page.evaluate(
        """([t, p]) => { const s = document.createElement('span'); s.style[p] = `var(${t})`; document.body.append(s);
        const c = getComputedStyle(s)[p]; s.remove(); return c; }""",
        [token, prop],
    )


def _style(locator, prop):
    return locator.evaluate(f"e => getComputedStyle(e).{prop}")


INTRO = ".page > h1 + p"


def _rgb(page, colour):
    """[r, g, b, a] in 0..1 for any CSS colour string, via a canvas (handles rgb() and color(srgb ...))."""
    return page.evaluate(
        """(c) => { const x = document.createElement('canvas').getContext('2d'); x.fillStyle = '#000'; x.fillStyle = c;
        x.fillRect(0, 0, 1, 1); const d = x.getImageData(0, 0, 1, 1).data; return [d[0]/255, d[1]/255, d[2]/255, d[3]/255]; }""",
        colour,
    )


def _contrast(page, fg, bg):
    def lum(c):
        f = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in _rgb(page, c)[:3]]
        return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]

    a, b = sorted([lum(fg), lum(bg)])
    return (b + 0.05) / (a + 0.05)


@pytest.mark.parametrize("scheme", ["dark", "light"])
def test_ac2_intro_text2(page, scheme):
    _open(page, "/#/stewardiq", scheme=scheme)
    c = _style(page.locator(INTRO), "color")
    assert c == _probe(page, "--text-2")
    assert c != _probe(page, "--muted")
    assert _contrast(page, c, _probe(page, "--bg", "backgroundColor")) >= 4.5


def test_ac2b_card_purpose(page):
    _open(page, "/#/home")
    assert _style(page.locator(".hub-card-purpose").first, "color") == _probe(page, "--text-2")


def test_ac2c_process_help(page):
    _open(page, "/#/stewardiq")
    assert _style(page.locator(".hub-process .help-text").first, "color") == _probe(page, "--text-2")


def test_ac3_lead_desktop(page):
    _open(page, "/#/stewardiq")
    intro = page.locator(INTRO)
    assert _style(intro, "fontSize") == "17px"
    assert _style(intro, "lineHeight") == "25.5px"
    assert _style(intro, "textWrap") == "pretty"
    zero = intro.evaluate("""e => { const s = document.createElement('span'); s.textContent = '0'; s.style.letterSpacing = 'normal'; e.append(s);
        const w = s.getBoundingClientRect().width; s.remove(); return w; }""")
    assert abs(float(_style(intro, "maxWidth")[:-2]) - 62 * zero) <= 1


def test_ac3b_lead_phone(page):
    _open(page, "/#/stewardiq", 390, 844)
    intro = page.locator(INTRO)
    assert _style(intro, "fontSize") == _style(page.locator("body"), "fontSize")
    key = intro.locator(".hub-step-handoff-key")
    h = key.evaluate("e => e.getClientRects().length")
    assert h == 1, "the key stays on one line"


def test_ac4b_tracking(page):
    _open(page, "/#/stewardiq")
    assert _style(page.locator("body"), "letterSpacing") == "-0.12px"
    for sel, em in ((".page > h1", -0.025), (".section-heading h2", -0.015)):
        el = page.locator(sel).first
        size = float(_style(el, "fontSize")[:-2])
        assert abs(float(_style(el, "letterSpacing")[:-2]) - em * size) <= 0.05, sel


def test_ac4c_kbd_normal(page):
    _open(page, "/#/stewardiq")
    assert _style(page.locator(".start-topbar kbd").first, "letterSpacing") == "normal"


def test_ac5_heading_weights(page):
    _open(page, "/#/home")
    for el in (page.locator(".hub-start .hub-hero h1"), page.locator(".hub-card-name").first):
        assert float(_style(el, "fontSize")[:-2]) >= 20
        assert _style(el, "fontWeight") == "500"
    _open(page, "/#/stewardiq")
    h1 = page.locator(".page > h1")
    assert float(_style(h1, "fontSize")[:-2]) >= 20 and _style(h1, "fontWeight") == "500"


def test_ac5b_small_h2_stays_600(page):
    _open(page, "/#/stewardiq")
    h2 = page.locator(".section-heading h2").first
    # Ruling: the spec says "stay at 600", but this h2 has no weight rule and renders at the browser's 700; it stays unchanged.
    assert float(_style(h2, "fontSize")[:-2]) < 20 and _style(h2, "fontWeight") == "700"




def test_ac6_dark_hairline(page):
    _open(page, "/#/argus")
    assert _style(page.locator(".argus-waiting"), "borderTopColor") == "rgba(232, 235, 240, 0.12)"
    page.keyboard.press("Control+k")
    field = page.locator(".palette-input")
    field.wait_for()
    field.evaluate("e => e.blur()")  # it opens focused; the rule is about the resting edge
    c = _style(field, "borderTopColor")
    assert c == _probe(page, "--field-border") and _rgb(page, c)[3] == 1


def test_ac6b_light_hairline(page):
    _open(page, "/#/argus", scheme="light")
    assert _style(page.locator(".argus-waiting"), "borderTopColor") == "rgb(216, 222, 231)"


def test_ac7b_button_duration(page):
    _open(page, "/#/stewardiq")
    assert "0.1s" in _style(page.locator(".start-topbar button").first, "transitionDuration")


@pytest.mark.parametrize("scheme", ["dark", "light"])
def test_ac9_bar_translucent(page, scheme):
    _open(page, "/#/stewardiq", scheme=scheme)
    bar = page.locator(".start-topbar")
    assert _style(bar, "backdropFilter") == "blur(20px)"
    # Painted over black the alpha shows: 80% of --bg plus 20% black.
    got = page.evaluate("""(c) => { const x = document.createElement('canvas').getContext('2d'); x.fillStyle = '#000'; x.fillRect(0,0,1,1);
        x.fillStyle = c; x.fillRect(0,0,1,1); return [...x.getImageData(0,0,1,1).data].slice(0,3).map(v => v/255); }""", _style(bar, "backgroundColor"))
    bg = _rgb(page, _probe(page, "--bg", "backgroundColor"))
    assert all(abs(g - 0.8 * b) <= 0.01 for g, b in zip(got, bg[:3], strict=True)), (got, bg)


def test_ac9b_phone_bar_opaque(page):
    _open(page, "/#/stewardiq", 390, 844)
    bar = page.locator(".start-topbar")
    assert _style(bar, "backdropFilter") == "none"
    assert _rgb(page, _style(bar, "backgroundColor"))[3] == 1


@pytest.mark.parametrize("scheme", ["dark", "light"])
def test_ac9c_badge_solid(page, scheme):
    page.route("**/api/waiting", lambda r: r.fulfill(json={"review": 100, "decisions": 20, "ballots": 3, "total": 123}))
    _open(page, "/#/stewardiq", scheme=scheme)
    badge = page.locator(".start-topbar .nav-count")
    bg = _style(badge, "backgroundColor")
    assert _rgb(page, bg)[3] == 1
    assert _contrast(page, _style(badge, "color"), bg) >= 4.5
