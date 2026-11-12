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


# --- defect 2: Presentations & Reports ---

def manifest(report_id, status, title, output_format="pptx"):
    return {"report_id": report_id, "created_at": "2026-11-11T10:00:00+00:00", "updated_at": "2026-11-11T10:00:00+00:00",
            "status": status, "title": title, "output_format": output_format, "input_tokens": 0, "output_tokens": 0,
            "output_files": []}


PLAN = {"title": "Plan title", "subtitle": "", "executive_summary": [], "sections": [], "appendix_sections": []}


def test_previous_reports_offer_discard_for_unfinished_and_never_for_finished(page):  # AC-100
    reports = [manifest("rpt_failed000000", "failed", "Broke"), manifest("rpt_done00000000", "completed", "Done")]
    page.route("**/api/reports", lambda route: route.fulfill(json={"reports": reports}))
    page.goto(f"{URL}/#/reporting")
    failed = page.get_by_role("row").filter(has_text="Broke")
    failed.get_by_role("button", name="Discard").wait_for()
    assert failed.get_by_role("button", name="Open").count() == 0
    done = page.get_by_role("row").filter(has_text="Done")
    assert done.get_by_text("Preview").count() == 1 and done.get_by_text("Download").count() == 1
    assert done.get_by_role("button", name="Discard").count() == 0


def test_drafting_shows_a_running_status_line_and_a_draft_can_be_opened_and_discarded(page):
    state = {"reports": [], "deleted": False, "drafting": None}
    draft = manifest("rpt_draft0000000", "plan_ready", "My draft")

    def reports(route):
        if route.request.method == "POST":
            state["drafting"] = route  # held open like the model call; answered below
        else:
            route.fulfill(json={"reports": state["reports"]})

    def one(route):
        if route.request.method == "DELETE":
            state.update(reports=[], deleted=True)
            route.fulfill(status=204)
        else:
            route.fulfill(json=draft)

    page.route("**/api/reports?render=false", reports)
    page.route("**/api/reports", reports)
    page.route("**/api/reports/rpt_draft0000000", one)
    page.route("**/api/reports/rpt_draft0000000/plan", lambda route: route.fulfill(json=PLAN))
    page.on("dialog", lambda dialog: dialog.accept())
    page.goto(f"{URL}/#/reporting")
    page.get_by_label("Title", exact=True).fill("My draft")
    page.get_by_label("Qualitative notes / findings").fill("Some notes")
    page.get_by_role("button", name="Draft content plan").click()

    status = page.get_by_role("status").filter(has_text="Drafting the content plan…")
    status.wait_for()
    assert "elapsed. This can take a few minutes; keep this page open." in status.inner_text()
    assert page.get_by_role("button", name="Drafting…").is_disabled()
    page.get_by_text("Drafting the content plan… 0:02 elapsed").wait_for()  # it counts up
    state["reports"] = [draft]
    state["drafting"].fulfill(json=draft)
    page.get_by_role("heading", name="3. Review & render").wait_for()
    assert status.count() == 0

    row = page.get_by_role("row").filter(has_text="My draft")
    row.get_by_role("button", name="Open").click()
    page.get_by_role("heading", name="3. Review & render").wait_for()
    row.get_by_role("button", name="Discard").click()
    page.get_by_text("No reports generated yet.").wait_for()
    assert state["deleted"] and page.get_by_role("heading", name="3. Review & render").count() == 0
