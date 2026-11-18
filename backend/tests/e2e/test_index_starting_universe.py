"""Index Construction, Starting universe card (spec index-starting-universe, PR 2): keyboard focus during a load.

Runs on the e2e stack's real API; the universe load is held by Playwright routing so the test can read focus mid-load.
"""

import pytest

from arp.config import Settings
from tests.e2e.test_showcase_themes_screens import URL, pytestmark  # noqa: F401 - pytestmark marks this module

SELECT = "#ix-universe select"
FOCUSED = f"document.activeElement === document.querySelector('{SELECT}')"


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.set_default_timeout(10_000)
        yield page
        browser.close()


def test_the_universe_select_keeps_focus_during_and_after_a_load(page):  # UI review on #449 (WCAG 2.4.3)
    held = []
    page.route("**/api/index/universes/*", lambda route: held.append(route))
    page.goto(f"{URL}/#/index")
    page.locator(f"{SELECT} option").nth(2).wait_for(state="attached")
    select = page.locator(SELECT)
    select.focus()

    page.keyboard.press("ArrowDown")  # the second option: a holdings file
    page.get_by_text("Loading").wait_for()
    assert page.evaluate(FOCUSED), "focus left the select when the load started"
    chosen = select.input_value()
    page.keyboard.press("ArrowDown")  # ignored while a load is in flight
    assert select.input_value() == chosen and len(held) == 1

    held.pop().continue_()
    page.locator("#ix-universe .help-text p").first.wait_for()
    assert page.evaluate(FOCUSED), "focus did not stay on the select after the load"

    page.keyboard.press("ArrowDown")  # the next file, whose load fails
    page.get_by_text("Loading").wait_for()
    held.pop().fulfill(status=500, json={"detail": "boom"})
    page.locator("#ix-universe .error-text").wait_for()
    assert "boom" in page.locator("#ix-universe .error-text").inner_text()
    assert select.input_value() == chosen, "a failed load keeps the previous universe"
    assert page.evaluate(FOCUSED), "focus did not stay on the select after a failed load"
