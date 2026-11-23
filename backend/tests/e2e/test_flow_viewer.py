"""Process flow viewer (docs/superpowers/specs/2026-11-23-process-flow-viewer.md) against the running app."""

import pytest

from tests.e2e.test_ui_polish_2 import URL, _open, page  # noqa: F401  (page is a fixture)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

T = "2026-11-22T10:00:00Z"
R1 = {"run_id": "r1", "run_type": "emerging_themes", "status": "running", "review_count": 0, "company_count": 480,
      "completed_count": 212, "failed_count": 0, "params": {}, "created_at": T, "updated_at": T}
R5 = {**R1, "run_id": "r5", "run_type": "calibration"}
SECTION = "section.hub-process:has(#process-thematic)"


def _start(pg, runs=(R1,), zoom=None, path="/#/designStrategy", width=1440, height=900):
    pg.route("**/api/runs*", lambda route: route.fulfill(json={"runs": list(runs)}))
    script = "localStorage.setItem('arp.orb', 'low');"
    if zoom is not None:
        script += f"localStorage.setItem('arp.flowZoom', {zoom!r});"
    pg.add_init_script(script)
    _open(pg, path, width, height)
    pg.locator(f"{SECTION} button.hub-step").first.wait_for(state="attached")
    return pg.locator(f"{SECTION} ol.hub-flow")


def _reading(pg):
    return pg.locator(f"{SECTION} [data-flow-zoom]").inner_text()


def _bar(pg, name):
    return pg.locator(f"{SECTION} [data-flow-zoom-bar]").get_by_role("button", name=name, exact=True)


def _widths(flow):
    return flow.evaluate("f => [...f.querySelectorAll('.hub-step')].map((s) => s.getBoundingClientRect().width)")


@pytest.mark.parametrize("width", [390, 1440])
def test_steps_keep_their_width_in_one_scrolling_row(page, width):  # noqa: F811
    flow = _start(page, width=width, height=844 if width == 390 else 900)
    assert all(abs(w - 180) <= 1 for w in _widths(flow)), _widths(flow)
    tops = flow.evaluate("f => [...f.querySelectorAll('.hub-step')].map((s) => s.getBoundingClientRect().top)")
    assert max(tops) - min(tops) <= 1, tops
    assert flow.evaluate("f => f.scrollWidth > f.clientWidth")
    assert page.evaluate("document.documentElement.scrollWidth") <= width
    assert flow.get_attribute("tabindex") == "0"
    assert flow.get_attribute("aria-label") == "Build a thematic portfolio steps"


def test_zoom_buttons_steps_limits_and_storage(page):  # noqa: F811
    flow = _start(page)
    names = page.locator(f"{SECTION} [data-flow-zoom-bar] button").evaluate_all("bs => bs.map((b) => b.getAttribute('aria-label'))")
    assert names == ["Zoom out", "Zoom in", "Reset zoom", "Fit to width"]
    assert _reading(page) == "100%" and _bar(page, "Reset zoom").is_disabled()
    _bar(page, "Zoom in").click()
    assert _reading(page) == "110%"
    assert abs(_widths(flow)[0] - 198) <= 1
    _bar(page, "Zoom in").click()
    assert page.evaluate("localStorage.getItem('arp.flowZoom')") == "120"
    presses = 0
    while not _bar(page, "Zoom in").is_disabled():
        _bar(page, "Zoom in").click()
        presses += 1
    assert (presses, _reading(page)) == (8, "200%")
    _bar(page, "Reset zoom").click()
    assert _reading(page) == "100%"
    _bar(page, "Fit to width").click()
    assert flow.evaluate("f => f.scrollWidth <= f.clientWidth"), flow.evaluate("f => [f.scrollWidth, f.clientWidth]")
    assert 50 <= int(_reading(page).rstrip("%")) <= 99


def test_stored_zoom_scales_the_whole_card(page):  # noqa: F811
    flow = _start(page, zoom="150")
    assert _reading(page) == "150%"
    assert abs(_widths(flow)[0] - 270) <= 1
    num = flow.locator(".hub-step-num").first.bounding_box()
    assert abs(num["width"] - 36) <= 1 and abs(num["height"] - 36) <= 1


@pytest.mark.parametrize("raw", ["abc", "10", "500"])
def test_bad_stored_zoom_counts_as_100(page, raw):  # noqa: F811
    _start(page, zoom=raw)
    assert _reading(page) == "100%"


def test_small_zoom_grows_cards_to_fill(page):  # noqa: F811
    flow = _start(page, zoom="50")
    assert flow.evaluate("f => f.scrollWidth === f.clientWidth")
    w = _widths(flow)
    assert max(w) - min(w) <= 1 and min(w) > 91, w


def test_ctrl_wheel_zooms_the_flow_not_the_page(page):  # noqa: F811
    _start(page)
    page.evaluate("window.__seen = []; window.addEventListener('wheel', (e) => window.__seen.push(e.defaultPrevented))")
    box = page.locator("#step-thematic-3").bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.keyboard.down("Control")
    page.mouse.wheel(0, -300)
    page.keyboard.up("Control")
    page.wait_for_function("() => document.querySelector('#process-thematic').closest('section').querySelector('[data-flow-zoom]').textContent === '130%'")
    assert page.evaluate("window.__seen") == [True]
    assert page.evaluate(f"document.elementFromPoint({x}, {y}).closest('#step-thematic-3') !== null")
    y0 = page.evaluate("window.scrollY")
    page.mouse.wheel(0, 100)  # no modifier: scrolls the page, does not zoom
    page.wait_for_function(f"window.scrollY > {y0}")
    assert _reading(page) == "130%"


def test_keys_zoom_and_scroll_and_leave_browser_zoom_alone(page):  # noqa: F811
    flow = _start(page)
    flow.focus()
    page.keyboard.press("+")
    assert _reading(page) == "110%"
    page.keyboard.press("-")
    page.keyboard.press("-")
    assert _reading(page) == "90%"
    page.locator("#step-thematic-2").focus()
    page.keyboard.press("0")
    assert _reading(page) == "100%"
    flow.focus()
    page.evaluate("window.__keys = []; window.addEventListener('keydown', (e) => e.key !== 'Control' && window.__keys.push(e.defaultPrevented))")
    page.keyboard.press("Control+=")
    page.keyboard.press("Control+-")
    assert _reading(page) == "100%" and page.evaluate("window.__keys") == [False, False]
    for _ in range(3):
        page.keyboard.press("ArrowRight")
    assert flow.evaluate("f => f.scrollLeft") > 0
    page.locator("#step-thematic-6").focus()
    assert page.locator("#step-thematic-6").evaluate("(s) => s.getBoundingClientRect().right <= s.closest('ol').getBoundingClientRect().right")


def test_drag_scrolls_and_does_not_open_the_step(page):  # noqa: F811
    flow = _start(page)
    box = page.locator("#step-thematic-1").bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    for i in range(1, 16):
        page.mouse.move(x - 10 * i, y)
    page.mouse.up()
    assert abs(flow.evaluate("f => f.scrollLeft") - 150) <= 2
    assert page.locator("#step-thematic-1").get_attribute("aria-expanded") == "false"
    assert page.evaluate("getSelection().toString()") == ""
    flow.evaluate("f => (f.scrollLeft = 0)")
    box = page.locator("#step-thematic-1").bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x - 3, y)
    page.mouse.up()
    assert page.locator("#step-thematic-1").get_attribute("aria-expanded") == "true"
    assert flow.evaluate("f => f.nextElementSibling.getAttribute('aria-label')") == "Define details"


def test_opens_on_the_running_step_once(page):  # noqa: F811
    flow = _start(page, runs=(R5,))
    page.locator("#step-thematic-5.hub-step-now").wait_for()
    inside = page.locator("#step-thematic-5").evaluate("""(s) => { const r = s.getBoundingClientRect(), f = s.closest('ol').getBoundingClientRect();
        return r.left >= f.left && r.right <= f.right; }""")
    assert inside and flow.evaluate("f => f.scrollLeft") > 0 and page.evaluate("window.scrollY") == 0
    flow.evaluate("f => (f.scrollLeft = 0)")
    page.wait_for_timeout(4000)
    assert flow.evaluate("f => f.scrollLeft") == 0


def test_first_step_running_stays_at_the_start(page):  # noqa: F811
    flow = _start(page)
    page.locator("#step-thematic-0.hub-step-now").wait_for()
    assert flow.evaluate("f => f.scrollLeft") == 0


def test_folded_flow_has_its_bar_inside_the_fold(page):  # noqa: F811
    _start(page, runs=(), path="/#/rdLab")
    assert page.locator("[data-flow-zoom-bar]:visible").count() == 0
    page.locator(SECTION).get_by_text("Show 7 steps").click()
    assert page.locator("[data-flow-zoom-bar]:visible").count() == 1


def test_pinch_zooms_the_flow_only(page):  # noqa: F811
    ctx = page.context.browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    try:
        pg = ctx.new_page()
        flow = _start(pg, width=390, height=844)
        box = flow.bounding_box()
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        cdp = ctx.new_cdp_session(pg)

        def touch(kind, half):
            pts = [] if kind == "touchEnd" else [{"x": cx - half, "y": cy, "id": 0}, {"x": cx + half, "y": cy, "id": 1}]
            cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": pts})

        touch("touchStart", 50)
        for half in range(55, 80, 5):
            touch("touchMove", half)
        touch("touchEnd", 75)
        assert 140 <= int(_reading(pg).rstrip("%")) <= 160, _reading(pg)
        assert pg.evaluate("window.visualViewport.scale") == 1
    finally:
        ctx.close()



def test_no_bar_before_the_runs_answer(page):  # noqa: F811
    """A foldable flow does not know yet whether it folds, so it shows no zoom bar until its runs answer."""

    def slow(route):
        page.wait_for_timeout(1500)
        route.fulfill(json={"runs": []})

    page.route("**/api/runs*", slow)
    page.add_init_script("localStorage.setItem('arp.orb', 'low');")
    page.goto(URL + "/#/rdLab")
    page.locator(f"{SECTION} button.hub-step").first.wait_for(state="attached")
    assert page.locator("[data-flow-zoom-bar]:visible").count() == 0


def test_release_outside_ends_the_drag(page):  # noqa: F811
    flow = _start(page)
    box = flow.bounding_box()
    page.mouse.move(box["x"] + 700, box["y"] + 3)
    page.mouse.down()
    page.mouse.move(box["x"] + 700, box["y"] - 20, steps=3)
    page.mouse.up()
    page.mouse.move(box["x"] + 700, box["y"] + 60)
    page.mouse.move(box["x"] + 500, box["y"] + 60, steps=10)  # no button held
    assert flow.evaluate("f => f.scrollLeft") == 0
    assert flow.get_attribute("data-dragging") is None


def test_reset_keeps_the_middle_of_stretched_cards(page):  # noqa: F811
    flow = _start(page, zoom="50")
    middle = "f => { const r = f.getBoundingClientRect(); return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2).closest('.hub-step')?.id; }"
    before = flow.evaluate(middle)
    _bar(page, "Reset zoom").click()
    assert _reading(page) == "100%"
    assert flow.evaluate(middle) == before


def test_bar_shows_when_runs_fail(page):  # noqa: F811
    page.route("**/api/runs*", lambda route: route.fulfill(status=500, body="boom"))
    page.add_init_script("localStorage.setItem('arp.orb', 'low');")
    _open(page, "/#/rdLab")
    page.get_by_text("Runs could not be loaded").wait_for()
    assert page.locator("ol.hub-flow:visible").count() == page.locator("[data-flow-zoom-bar]:visible").count() > 0
