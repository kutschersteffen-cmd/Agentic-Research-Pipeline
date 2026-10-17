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


def test_start_page_signs_in_and_loads_without_errors(page):
    page.goto(URL)
    page.wait_for_load_state("networkidle")

    assert page.title() == "Start · ARP"
    assert page.get_by_text("Signed in as dev (approver)").is_visible()  # /api/me answered
    assert page.console_errors == []


def test_navigating_to_the_review_queue_loads_it_from_the_api(page):
    page.goto(URL)
    page.wait_for_load_state("networkidle")

    with page.expect_response(lambda r: "/api/review" in r.url) as resp:
        page.get_by_role("navigation").get_by_text("Review Queue").first.click()
    assert resp.value.ok

    page.wait_for_load_state("networkidle")
    assert page.title() == "Review Queue · ARP"
    assert page.get_by_role("heading", name="Review Queue").is_visible()
    assert page.console_errors == []
