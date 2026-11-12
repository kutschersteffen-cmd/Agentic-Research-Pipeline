"""showcase-stewardship-fixes PR A, the "unit (browser)" rows: the running app with the named API routes stubbed."""

import os
import re

import pytest

from arp.config import Settings

URL = os.environ.get("ARP_E2E_URL")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

RUN = {"run_id": "identity_failed1", "run_type": "identity", "created_at": "2026-11-11T09:00:00+00:00",
       "updated_at": "2026-11-11T09:05:00+00:00", "status": "partially_completed", "params": {}, "company_count": 2,
       "completed_count": 1, "failed_count": 1, "review_count": 0, "input_tokens": 0, "output_tokens": 0,
       "cache_read_tokens": 0, "cache_creation_tokens": 0, "estimated_cost_usd": 0.0, "batch_saved_usd": 0.0,
       "batch_wait": None, "model": None, "verifier_model": None, "error": None, "cancel_requested": False}


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(10_000)
        yield page
        browser.close()


def open_failure(page, company_errors):
    page.route(re.compile(r".*/api/runs(\?.*)?$"), lambda r: r.fulfill(json={"runs": [RUN]}))
    page.route("**/api/runs/identity_failed1/failure", lambda r: r.fulfill(json={
        "run_id": "identity_failed1", "status": "partially_completed", "error": None, "traceback": None,
        "company_errors": company_errors}))
    page.goto(f"{URL}/#/history")
    page.get_by_role("button", name="Details for identity_failed1").click()
    return page.locator(".failure-details")


def test_company_traceback_is_shown(page):  # AC-19
    details = open_failure(page, [{"key": "acme", "error": "ReadTimeout",
                                   "traceback": "Traceback (most recent call last): X"}])
    details.get_by_text("Traceback (most recent call last): X").wait_for()
    assert "acme" in details.inner_text()
    assert "No traceback was recorded for this run." not in details.inner_text()


def test_no_traceback_anywhere_says_so(page):  # AC-20 (must not change)
    details = open_failure(page, [{"key": "acme", "error": "ReadTimeout", "traceback": None}])
    details.get_by_text("No traceback was recorded for this run.").wait_for()


NOTE_OFF = ("Re-checking sources is switched off on this server, so a derivation uses only facts entered by hand and "
            "documents already stored. Cells without facts come out as Not rated.")


def with_refresh(enabled):
    """Pass the real answer through with `refresh_enabled` set."""
    def handler(route):
        body = route.fetch().json()
        route.fulfill(json={**body, "refresh_enabled": enabled})
    return handler


@pytest.mark.parametrize("enabled", [False, True])
def test_refresh_note_by_the_derive_buttons(page, enabled):  # AC-24, AC-25 (switch off), AC-27 (on)
    page.route("**/api/transition-barrier/matrix", with_refresh(enabled))
    page.route("**/api/transition-barrier/cells/STL-R1/European%20Union", with_refresh(enabled))
    page.goto(f"{URL}/#/transitionBarrier")
    page.get_by_role("button", name="STL-R1", exact=True).click()
    page.get_by_role("button", name="Derive all regions").wait_for()
    assert page.get_by_text(NOTE_OFF).count() == (0 if enabled else 1)
    page.goto(f"{URL}/#/transitionBarrier/cell/STL-R1/European%20Union")
    page.get_by_role("button", name="Derive this cell").wait_for()
    assert page.get_by_text(NOTE_OFF).count() == (0 if enabled else 1)
