"""Browser flow tests against the running app (backend/scripts/e2e_stack.sh up).

Opt-in like the live Superset suite: they skip unless ARP_E2E_URL points at the frontend. The
holdout acceptance tests and the evaluator agent drive the same stack the same way.
"""

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
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.console_errors = []
        page.on("console", lambda m: m.type == "error" and page.console_errors.append(m.text))
        yield page
        browser.close()


def test_opening_arp_lands_on_the_landing_page(page):
    # Night Desk release 5: no page in the address shows the landing page, not the app.
    page.goto(URL)
    page.wait_for_load_state("networkidle")

    assert page.get_by_role("heading", name="Company research and stewardship at scale.").is_visible()
    assert page.locator(".app-sidebar").count() == 0
    page.get_by_role("link", name="Open ARP →").click()
    # The app sets the tab title in an effect after it mounts, so wait for it rather than for the network.
    page.wait_for_function("document.title === 'Start · ARP'", timeout=10_000)
    # The start page has its own top bar instead of the sidebar (spec 2026-11-15-start-page-simplified).
    assert page.locator(".start-topbar").count() == 1
    assert page.console_errors == []


def test_start_page_signs_in_and_loads_without_errors(page):
    page.goto(URL + "/#/home")
    page.wait_for_load_state("networkidle")

    assert page.title() == "Start · ARP"
    page.locator(".start-topbar-me").click()  # sign-in details live in the start page's user menu
    assert page.get_by_text("Signed in as dev (approver)").is_visible()  # /api/me answered
    assert page.console_errors == []


def test_start_page_user_menu_returns_focus_after_an_outside_click(page):
    # Spec 2026-11-15-start-page-simplified, AC-8d/AC-8e.
    page.goto(URL + "/#/home")
    page.wait_for_load_state("networkidle")
    page.locator(".start-topbar-me").click()
    page.locator(".hub-hero").click(position={"x": 2, "y": 2})  # outside the menu, on nothing focusable
    assert not page.locator(".start-topbar-user .start-topbar-pop").is_visible()
    # Focus returns one tick after the press (the press itself focuses the page first).
    page.wait_for_function("() => document.activeElement.classList.contains('start-topbar-me')", timeout=2_000)


def test_start_top_bar_never_pushes_a_narrow_phone_sideways(page):
    # Spec 2026-11-15-start-page-simplified, AC-16a, at 360px: a Review Queue badge must not widen the page.
    page.set_viewport_size({"width": 360, "height": 800})
    page.goto(URL + "/#/home")
    page.wait_for_load_state("networkidle")
    assert page.evaluate("() => document.documentElement.scrollWidth") <= 360


def test_navigating_to_the_review_queue_loads_it_from_the_api(page):
    page.goto(URL + "/#/home")
    page.wait_for_load_state("networkidle")

    with page.expect_response(lambda r: "/api/review" in r.url) as resp:
        page.get_by_role("navigation").get_by_text("Review Queue").first.click()
    assert resp.value.ok

    page.wait_for_load_state("networkidle")
    assert page.title() == "Review Queue · ARP"
    assert page.get_by_role("heading", name="Review Queue").is_visible()
    assert page.console_errors == []


# App-wide top bar (spec 2026-11-15-app-wide-top-bar): the phone drawer is gone, so
# test_phone_drawer_takes_focus_on_a_screen_without_a_sidebar_link is retired.

ROUTES = ["/#/home", "/#/review", "/#/stewardiq", "/#/argus", "/#/history", "/#/library", "/#/arcade"]


def _open(page, path, width=1440, height=900):
    page.set_viewport_size({"width": width, "height": height})
    page.goto(URL + path)
    page.wait_for_load_state("networkidle")


@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_every_route_has_one_banner_and_no_sidebar(page, width, height):
    # AC-1, AC-1b.
    for path in ROUTES:
        _open(page, path, width, height)
        assert page.get_by_role("banner").count() == 1, path
        assert page.get_by_role("banner").get_by_role("link", name="ARP start").count() == 1, path
        assert page.locator(".app-sidebar, .app-topbar").count() == 0, path
        assert page.get_by_role("button", name="Open navigation").count() == 0, path


def test_workspace_row_on_argus(page):
    # AC-11.
    _open(page, "/#/argus")
    row = page.get_by_role("navigation", name="Argus screens")
    assert row.count() == 1
    links = row.get_by_role("link")
    got = [(links.nth(i).inner_text().strip(), links.nth(i).get_attribute("href")) for i in range(links.count())]
    assert got == [("Argus", "#/argus"), ("New extraction", "#/argus/new"), ("Walkthrough", "#/argusWalkthrough"),
                   ("XBRL Facts", "#/xbrl"), ("Review Queue", "#/review")]
    assert links.nth(0).get_attribute("aria-current") == "page"


def test_no_row_on_review_detail(page):
    _open(page, "/#/review/extraction/x")
    assert page.locator(".ws-row").count() == 0


@pytest.mark.parametrize("width", [800, 1024])
def test_top_bar_fits_tablet_widths(page, width):
    for path in ["/#/stewardiq", "/#/history"]:
        _open(page, path, width, 900)
        assert page.evaluate("() => document.documentElement.scrollWidth") <= width, path


def test_top_bar_two_rows_at_360(page):
    # AC-16, with a long Review Queue badge: one reviewable run reports 123 items.
    def long_badge(route):
        resp = route.fetch()
        body = resp.json()
        runs = body.get("runs", [])
        for r in runs:
            r["review_count"] = 0
        runs.insert(0, {**(runs[0] if runs else {}), "run_id": "e2e-badge", "run_type": "extraction",
                        "status": "completed", "review_count": 123, "updated_at": "2026-11-15T00:00:00Z"})
        route.fulfill(response=resp, json={**body, "runs": runs})

    page.route("**/api/runs", long_badge)
    _open(page, "/#/stewardiq", 360, 800)
    assert page.locator(".start-topbar .nav-count").get_attribute("aria-label") == "123 review items waiting on you"
    boxes = page.evaluate("""() => [...document.querySelectorAll('.start-topbar a, .start-topbar button')]
        .filter((e) => e.offsetParent !== null && !e.closest('[hidden]')).map((e) => e.getBoundingClientRect())
        .map((r) => ({top: Math.round(r.top), h: r.height}))""")
    assert all(b["h"] >= 44 for b in boxes), boxes
    tops = sorted({b["top"] for b in boxes})
    rows = [t for i, t in enumerate(tops) if i == 0 or t - tops[i - 1] > 2]
    assert len(rows) == 2, boxes
    assert page.evaluate("() => document.documentElement.scrollWidth") <= 360
