"""UI polish 1 (docs/superpowers/specs/2026-11-15-ui-polish-1-design.md) against the running app."""

import json
import os

import pytest

from arp.config import Settings
from tests.e2e.test_showcase_stewardship_side import _vote, open_voting

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
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(10_000)
        yield page
        browser.close()


def _open(page, path, width=1440, height=900):
    page.set_viewport_size({"width": width, "height": height})
    page.goto(URL + path)
    page.wait_for_load_state("networkidle")


def _user_menu(page):
    page.locator(".start-topbar-me").click()
    return page.locator(".start-topbar-user .start-topbar-pop")


# --- F1: the signed-in name is the reviewer ---


def test_ac1_menu_shows_signed_in_only(page):
    _open(page, "/#/history")
    pop = _user_menu(page)
    assert pop.get_by_text("Signed in as dev (approver)").is_visible()
    assert pop.locator(".theme-switch").count() == 1
    assert pop.get_by_role("link", name="Arcade").count() == 1
    assert pop.get_by_label("Reviewing as").count() == 0


def test_ac1b_reviewer_follows_me(page):
    page.add_init_script("localStorage.setItem('arp.reviewer', 'Ana')")
    _open(page, "/#/history")
    page.wait_for_function("() => localStorage.getItem('arp.reviewer') === 'dev'", timeout=5_000)


def test_ac1c_signed_out_keeps_field(page):
    page.route("**/api/me", lambda r: r.fulfill(status=401, json={"detail": "Not signed in"}))
    _open(page, "/#/history")
    assert _user_menu(page).get_by_label("Reviewing as").count() == 1


def test_ac1d_vote_records_the_signed_in_name(page):
    page.add_init_script("localStorage.setItem('arp.reviewer', 'Ana')")
    posted = []

    def review(route):
        posted.append(json.loads(route.request.post_data))
        route.fulfill(json={"status": "recorded"})

    open_voting(page, [_vote(3)], on_review=review)
    page.wait_for_function("() => localStorage.getItem('arp.reviewer') === 'dev'")  # /api/me has answered
    page.get_by_role("button", name="Approve 1 routine…").click()
    dialog = page.get_by_role("dialog")
    assert "not verified by a login" not in dialog.inner_text()
    assert "Recorded against your sign-in: dev" in dialog.inner_text()
    page.get_by_role("button", name="Approve 1", exact=True).click()
    page.wait_for_timeout(500)
    assert [p["reviewer"] for p in posted] == ["dev"]


def test_reviewer_field_returns_after_sign_out(page):
    _open(page, "/#/history")
    page.wait_for_function("() => localStorage.getItem('arp.reviewer') === 'dev'", timeout=5_000)
    page.route("**/api/me", lambda r: r.fulfill(status=401, json={"detail": "Not signed in"}))
    page.reload()
    page.wait_for_load_state("networkidle")
    assert _user_menu(page).get_by_label("Reviewing as").input_value() == "dev"


# --- F3, F4, F8, F9: the shell ---


@pytest.mark.parametrize("width", [1440, 900])
def test_ac3_row_aligns_with_content(page, width):
    _open(page, "/#/argus", width, 900)
    row = page.get_by_role("navigation", name="Argus screens").get_by_role("link").first.bounding_box()
    h1 = page.locator("main h1").first.bounding_box()
    assert abs(row["x"] - h1["x"]) <= 1, (row, h1)


def test_ac3b_row_gutter_phone(page):
    _open(page, "/#/argus", 390, 844)
    row = page.get_by_role("navigation", name="Argus screens").get_by_role("link").first.bounding_box()
    assert abs(row["x"] - 16) <= 1, row


def test_ac4_closed_menus_not_tabbable(page):
    _open(page, "/#/stewardiq")
    page.get_by_role("link", name="ARP start").focus()
    for _ in range(12):
        page.keyboard.press("Tab")
        assert not page.evaluate("() => !!document.activeElement.closest('.start-topbar-pop')")


def test_ac8_badge_padding(page):
    from tests.e2e.test_app_smoke import _long_badge

    page.route("**/api/waiting", _long_badge)
    _open(page, "/#/stewardiq")
    badge = page.locator(".start-topbar .nav-count")
    assert badge.evaluate("e => getComputedStyle(e).paddingTop") == "2px"
    assert badge.bounding_box()["height"] <= 24


@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_ac9_menu_shows_purposes(page, width, height):
    _open(page, "/#/history", width, height)
    page.get_by_role("button", name="Workspaces").click()
    pop = page.locator(".start-topbar-spaces-pop")
    pop.get_by_role("link").first.wait_for()
    assert "Every workspace at a glance" in pop.get_by_role("link", name="Start").inner_text()
    argus = pop.get_by_role("link", name="Argus")
    assert "Extract cited data points from disclosures and score them." in argus.inner_text()
    size = argus.locator(".start-topbar-purpose").evaluate("e => getComputedStyle(e).fontSize")
    xs = page.evaluate("() => { const d = document.createElement('span'); d.style.fontSize = 'var(--text-xs)'; document.body.append(d); const s = getComputedStyle(d).fontSize; d.remove(); return s; }")
    assert size == xs
    assert abs(pop.bounding_box()["width"] - 280) <= 1 or width < 400


# --- F2, F5, F7, F10, F11: workspace and Argus pages ---


def test_ac2_argus_head_has_no_duplicate_links(page):
    _open(page, "/#/argus")
    head = page.locator(".argus-head")
    assert head.get_by_role("link", name="Walkthrough").count() == 0
    assert head.get_by_role("link", name="XBRL Facts").count() == 0
    assert head.get_by_role("button", name="Start new extraction").count() == 1
    row = page.get_by_role("navigation", name="Argus screens")
    assert row.get_by_role("link", name="Walkthrough").count() == 1
    assert row.get_by_role("link", name="XBRL Facts").count() == 1


def test_ac5_process_chips_below_heading_on_phone(page):
    _open(page, "/#/stewardiq", 390, 844)
    for sec in page.locator(".hub-process").all():
        h2 = sec.locator("h2").bounding_box()
        chip = sec.locator(".hub-process-meta").bounding_box()
        assert chip["y"] >= h2["y"] + h2["height"] - 1, (h2, chip)


def test_ac10_captions_and_passes_on(page):
    _open(page, "/#/home")
    import re
    for cap in page.locator(".hub-cards .hub-card-cap").all_inner_texts():  # the Cockpit entry below the cards is not a workspace card
        assert re.fullmatch(r"\d+ process(es)?", cap.strip(), re.I), cap
    _open(page, "/#/stewardiq")
    text = page.locator(".hub-step").all_text_contents()  # folded processes' steps too
    assert not any("Hands on:" in t for t in text)
    assert any("Passes on:" in t for t in text)


def test_ac11b_failed_line_links_to_run_history(page):
    def runs(route):
        resp = route.fetch()
        body = resp.json()
        body["runs"] = [{**(body["runs"][0] if body.get("runs") else {}), "run_id": "e2e-spot-failed", "run_type": "emerging_themes",
                         "status": "failed", "review_count": 0, "updated_at": "2026-11-16T00:00:00Z",
                         "created_at": "2026-11-16T00:00:00Z"}] + body.get("runs", [])
        route.fulfill(response=resp, json=body)

    page.route("**/api/runs", runs)
    _open(page, "/#/rdLab")
    line = page.locator(".hub-failed-line")
    assert line.count() == 1  # only "Launch a thematic product" watches emerging_themes
    assert line.inner_text().startswith("Last run failed: Launch a thematic product.")
    assert line.get_by_role("link", name="Open Run history →").get_attribute("href") == "#/history"
    low = page.evaluate("() => { const d = document.createElement('span'); d.style.color = 'var(--low)'; document.body.append(d); const c = getComputedStyle(d).color; d.remove(); return c; }")
    assert line.evaluate("e => getComputedStyle(e).color") == low


@pytest.mark.parametrize("path,title", [("/#/history", "Run History"), ("/#/library", "Data Library")])
def test_ac6_hub_title_shows_and_links_are_tabs(page, path, title):
    _open(page, path)
    h1 = page.locator("main h1").first
    assert h1.inner_text() == title
    box = h1.bounding_box()
    assert box and box["width"] > 1 and box["height"] > 1, "the page's h1 is visible"
    sizes = page.locator(".hub-nav .nav-tab").evaluate_all("els => els.map(e => getComputedStyle(e).fontSize)")
    assert sizes and set(sizes) == {"14px"}, sizes
