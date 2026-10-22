"""RFP project page against the running app, with its API stubbed by Playwright routing."""

import os

import pytest

from arp.config import Settings

URL = os.environ.get("ARP_E2E_URL")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]


def project(run_status):
    return {"id": 1, "investor": "Nordic Pension Fund", "due_date": None, "filename": "rfp_in.xlsx", "run_status": run_status,
            "not_located": 0, "question_count": 0, "approved_count": 0, "questions": []}


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(10_000)
        yield page
        browser.close()


def test_auto_fill_again_is_polled_until_done(page):
    """The project was `done` when the page opened; after "Auto-fill again" it polls until the run ends."""
    state = {"status": "done"}

    def get(route):
        if route.request.method == "GET":
            route.fulfill(json=project(state["status"]))
            state["status"] = "done" if state["status"] == "drafting" else state["status"]  # done on the next poll
        else:
            route.fallback()

    def autofill(route):
        state["status"] = "drafting"
        route.fulfill(json=project("drafting"))

    page.route("**/api/rfp/projects/1", get)
    page.route("**/api/rfp/projects/1/autofill", autofill)
    page.goto(f"{URL}/#/rfp/1")
    page.get_by_text("· done").wait_for()
    page.get_by_role("button", name="Auto-fill again").click()
    page.get_by_text("· drafting").wait_for()
    page.get_by_text("· done").wait_for()  # without a reload
    assert page.get_by_role("button", name="Auto-fill again").is_enabled()


def test_a_run_stuck_by_a_restart_can_be_started_again(page):  # PR #215 review item B1
    """A project left `drafting` (no worker since a restart): the button stays enabled and the server decides."""
    state = {"status": "drafting", "posted": False}

    def get(route):
        if route.request.method == "GET":
            route.fulfill(json=project(state["status"]))
        else:
            route.fallback()

    def autofill(route):
        state["posted"], state["status"] = True, "done"
        route.fulfill(json=project("done"))

    page.route("**/api/rfp/projects/1", get)
    page.route("**/api/rfp/projects/1/autofill", autofill)
    page.goto(f"{URL}/#/rfp/1")
    page.get_by_text("· drafting").wait_for()
    page.get_by_role("button", name="Auto-fill again").click()
    page.get_by_text("· done").wait_for()
    assert state["posted"]
