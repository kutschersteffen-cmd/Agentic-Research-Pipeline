"""Showcase fixes for the portfolio screens that are pure markup, against the running app with the named
API calls answered by the test (spec showcase-portfolio-fixes)."""

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
        page.set_default_timeout(10_000)
        yield page
        browser.close()


def card(page, heading):
    return page.locator("section.card", has=page.get_by_role("heading", name=heading, exact=True))


# --- defect 9: opening tab and Company Profiles ---

def test_risk_monitoring_opens_on_monitoring_and_alerts(page):
    page.goto(f"{URL}/#/portfolio-monitoring")
    assert page.get_by_role("button", name="Monitoring & Alerts").get_attribute("aria-pressed") == "true"
    page.get_by_role("heading", name="Add a monitoring rule").wait_for()


def test_company_profiles_without_superset_shows_help_not_an_error(page):
    page.route("**/api/bi/dashboards", lambda route: route.fulfill(status=503, json={"detail": "Superset is not configured"}))
    page.goto(f"{URL}/#/portfolio-monitoring/profiles")
    profile = card(page, "Profile dashboard")
    profile.get_by_text("Dashboards are not set up on this server. Ask your administrator.").wait_for()
    assert profile.get_by_role("alert").count() == 0
    assert "could not be loaded" not in profile.inner_text()


def test_company_profiles_still_reports_other_errors(page):  # AC-83
    page.route("**/api/bi/dashboards", lambda route: route.fulfill(status=500, json={"detail": "boom"}))
    page.goto(f"{URL}/#/portfolio-monitoring/profiles")
    alert = card(page, "Profile dashboard").get_by_role("alert")
    alert.wait_for()
    assert alert.inner_text() == "The profile dashboard could not be loaded: boom"
