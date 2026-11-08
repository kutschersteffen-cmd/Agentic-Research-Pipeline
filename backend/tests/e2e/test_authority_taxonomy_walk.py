"""Authority-taxonomy walk against the real API with stand-ins (no route stubs).

Start the stack with the fixture folders:
  ARP_STANDINS_DIR=backend/tests/fixtures/authority_taxonomy_ui/standins \
  ARP_VALUE_CHAIN_DIR=backend/tests/fixtures/authority_taxonomy_ui/io \
  bash backend/scripts/e2e_stack.sh up
and run with ARP_E2E_URL=http://localhost:5173 and the same ARP_STANDINS_DIR exported (the test skips without it). Needs no model key (stand-ins refuse one).
"""

import os

import pytest

from arp.config import Settings

URL = os.environ.get("ARP_E2E_URL")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
    # CI's E2E job starts the stack without stand-ins; run this in the same shell that started it with them.
    pytest.mark.skipif(not os.environ.get("ARP_STANDINS_DIR"), reason="ARP_STANDINS_DIR not set -- stack has no stand-ins"),
]


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(30_000)
        yield page
        browser.close()


def test_hydrogen_walk(page):
    page.goto(f"{URL}/#/taxonomy/authority")
    page.get_by_label("Theme name").fill("Hydrogen")
    page.get_by_label("Theme key").select_option("hydrogen")
    page.get_by_label("Scope").fill("S1")
    page.get_by_label("Source guidance").fill("G1")
    page.get_by_label("Value chain").check()
    page.get_by_role("button", name="Start").click()

    page.wait_for_url("**/#/taxonomy/authority/*")
    run_url = page.url
    hydrogen = page.get_by_role("listitem").filter(has_text="EU Taxonomy hydrogen")
    blocked = page.get_by_role("listitem").filter(has_text="Blocked report")
    hydrogen.wait_for()
    assert "From library" in hydrogen.inner_text()
    blocked.get_by_text("Not fetchable").wait_for()
    assert hydrogen.get_by_role("checkbox").is_checked()
    assert not blocked.get_by_role("checkbox").is_checked()

    page.get_by_role("button", name="Build draft").click()

    page.get_by_role("heading", name="Theme description").wait_for()
    assert page.locator('li[aria-label^="Activity "]').count() == 2
    first = page.locator('li[aria-label^="Activity "]').first
    assert first.get_by_label("Value-chain role").input_value() == "core"
    assert first.locator(".badge", has_text="exiobase").count() == 1
    rows = page.locator("section", has=page.get_by_role("heading", name="Checklist report")).locator("tbody tr")
    assert rows.count() == 1
    cells = rows.first.locator("td").all_inner_texts()[1:]
    assert cells == ["not in source", "found", "not in source", "not in source", "not in source", "not in source", "not in source", "found"]
    assert len(page.get_by_text("Hydrogen revenue share").all()) >= 1

    first.get_by_label("Value-chain role").select_option("upstream")
    page.get_by_role("button", name="Save").click()
    page.get_by_role("button", name="Save").wait_for(state="visible")
    page.goto(run_url)
    page.reload()
    page.locator('li[aria-label^="Activity "]').first.wait_for()
    assert page.locator('li[aria-label^="Activity "]').first.get_by_label("Value-chain role").input_value() == "upstream"

    page.get_by_role("button", name="Accept").click()
    page.get_by_text("Accepted as taxonomy").wait_for()
