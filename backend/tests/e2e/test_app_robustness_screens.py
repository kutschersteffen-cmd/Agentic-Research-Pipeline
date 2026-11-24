"""Screen failures say so once (spec app-robustness, slice 2): Emerging Themes, Taxonomy Library, against the running
app with the API stubbed by Playwright routing."""

import json
import os

import pytest

from arp.config import Settings

URL = os.environ.get("ARP_E2E_URL")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

RUN = {"run_id": "et_1", "run_type": "emerging_themes", "status": "completed", "review_count": 0, "created_at": "2026-11-24T10:00:00Z"}


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(10_000)
        yield page
        browser.close()


def fail(page, pattern):
    page.route(pattern, lambda r: r.fulfill(status=500, content_type="application/json", body=json.dumps({"detail": "boom"})))


def ok(page, pattern, body):
    page.route(pattern, lambda r: r.fulfill(content_type="application/json", body=json.dumps(body)))


def test_recent_scans_failure_shows_one_line(page):
    fail(page, "**/api/runs?run_type=emerging_themes*")
    ok(page, "**/api/emerging-themes/schedule", {"enabled": False, "interval_hours": 24, "universe_path": None, "last_run_id": None})
    page.goto(f"{URL}/#/emergingThemes")
    page.get_by_role("alert").filter(has_text="Recent scans could not be loaded: boom").wait_for()
    assert page.get_by_role("alert").count() == 1


def test_schedule_failure_shows_in_its_card(page):
    ok(page, "**/api/runs?run_type=emerging_themes*", {"runs": []})
    fail(page, "**/api/emerging-themes/schedule")
    page.goto(f"{URL}/#/emergingThemes")
    page.get_by_role("alert").filter(has_text="The schedule could not be loaded: boom").wait_for()
    assert page.get_by_role("alert").count() == 1


def test_candidates_failure_shows_one_line(page):
    ok(page, "**/api/runs?run_type=emerging_themes*", {"runs": [RUN]})
    ok(page, "**/api/emerging-themes/schedule", {"enabled": False, "interval_hours": 24, "universe_path": None, "last_run_id": None})
    fail(page, "**/api/emerging-themes/runs/et_1/candidates*")
    page.goto(f"{URL}/#/emergingThemes")
    page.get_by_role("button", name="View candidates").click()
    page.get_by_role("alert").filter(has_text="Candidates could not be loaded: boom").wait_for()
    assert page.get_by_role("alert").count() == 1


def test_taxonomy_list_failure_is_shown(page):
    fail(page, "**/api/taxonomies")
    page.goto(f"{URL}/#/taxonomy")
    page.get_by_role("alert").filter(has_text="The taxonomy list could not be loaded: boom").wait_for()
