"""Showcase fixes, R&D Lab screens (spec showcase-themes-fixes, PR 1), with the API stubbed by Playwright routing."""

import os

import pytest

from arp.config import Settings

URL = os.environ.get("ARP_E2E_URL")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]
LONG = "x" * 600  # 600 characters without a line break


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.set_default_timeout(10_000)
        yield page
        browser.close()


def manifest(status="completed", **kw):
    return {"run_id": "run_t", "run_type": "theme", "created_at": "2026-11-11T09:00:00Z", "updated_at": "2026-11-11T09:00:00Z",
            "status": status, "params": {}, "company_count": 5, "completed_count": 0, "failed_count": 0, "review_count": 0,
            "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0, **kw}


def citation(**kw):
    return {"doc_id": "d1", "doc_type": "10-K", "quote": "Revenue rose", "grounded": True, "company_id": "c1",
            "source_filename": None, "source_url": None, "page": None, "sheet": None, "match_method": "exact", **kw}


def match(citations, rationale="Builds batteries."):
    return {"company_id": "c1", "name": "Acme", "ticker": None, "activity_id": "a1", "activity_name": "Batteries",
            "verdict": "include", "exposure_estimate": "significant", "confidence": 0.8, "revenue_exposure": None,
            "indirect_exposure": None, "flagged_for_review": False, "adjudicator_rationale": rationale, "citations": citations}


def theme_results(page, *citations, rationale="Builds batteries."):
    page.route("**/api/runs/run_t", lambda r: r.fulfill(json=manifest()))
    page.route("**/api/themes/runs/run_t/results*", lambda r: r.fulfill(json={"results": [match(list(citations), rationale)]}))
    page.goto(f"{URL}/#/theme/run_t")
    page.get_by_role("cell", name="Acme").click()


def test_web_citation_links_to_its_url(page):  # AC-40
    theme_results(page, citation(source_url="https://www.sec.gov/x.htm"))
    link = page.get_by_role("link", name="view source")
    assert (link.get_attribute("href"), link.get_attribute("target"), link.get_attribute("rel")) == (
        "https://www.sec.gov/x.htm", "_blank", "noopener noreferrer")


@pytest.mark.parametrize("url", [None, "javascript:alert(1)"])
def test_no_view_source_without_a_safe_source(page, url):  # AC-41, AC-113
    theme_results(page, citation(source_url=url))
    page.get_by_text('"Revenue rose"').wait_for()
    assert page.get_by_text("view source").count() == 0


def test_no_empty_source_panel(page):  # AC-42, AC-43
    theme_results(page, citation())
    page.get_by_text('"Revenue rose"').wait_for()
    assert page.get_by_text('Click "view source" on any citation').count() == 0
    table = page.locator(".split-review .table-wrap").bounding_box()["width"]
    column = page.locator(".split-review").bounding_box()["width"]
    assert table >= 0.9 * column


def test_stored_file_still_opens_the_panel(page):  # AC-114
    theme_results(page, citation(source_filename="r.pdf"))
    page.get_by_role("button", name="view source").click()
    page.locator(".source-panel").wait_for()
    assert page.locator(".split-review .source-panel").count() == 1


def _fits(page):
    cell = page.locator("td.detail-cell").first
    cell.wait_for()
    return cell.evaluate("el => el.scrollWidth <= el.clientWidth")


def test_long_rationale_wraps(page):  # AC-115
    theme_results(page, citation(), rationale=LONG)
    assert _fits(page)


def test_long_candidate_detail_wraps(page):  # AC-44
    candidate = {"theme_id": "e1", "theme_name": "Heat pumps", "description": "d", "first_detected_date": "2026-11-11",
                 "signal_velocity": 1.0, "breadth": 0.1, "persistence": 0, "novelty": 1.0, "corroborating_sources": [],
                 "candidate_sectors_companies": [], "rationale": LONG, "economic_rationale": "e", "confidence_score": 1.0,
                 "action_score": 0.0, "xbrl_corroboration": [], "materiality": 0.0, "contradiction": 0.0,
                 "contradiction_evidence": [], "company_exposure": [], "context_brief": None, "status": "candidate",
                 "cluster_id": "k", "run_id": "et1", "created_at": "2026-11-11T09:00:00Z"}
    page.route("**/api/runs?run_type=emerging_themes",
               lambda r: r.fulfill(json={"runs": [manifest(run_id="et1", run_type="emerging_themes")]}))
    page.route("**/api/emerging-themes/runs/et1/candidates", lambda r: r.fulfill(json={"candidates": [candidate]}))
    page.goto(f"{URL}/#/emergingThemes")
    page.get_by_role("button", name="View candidates").click()
    page.get_by_role("cell", name="Heat pumps").click()
    assert _fits(page)


class Polls:
    def __init__(self, page, answers):
        self.count, self.answers = 0, answers
        page.route("**/api/runs/run_t", self.handle)

    def handle(self, route):
        self.count += 1
        status, body = self.answers[min(self.count, len(self.answers)) - 1]
        route.fulfill(status=status, json=body)


def _running_card(page, answers):
    polls = Polls(page, answers)
    page.route("**/api/themes/runs/run_t/results*", lambda r: r.fulfill(json={"results": []}))
    page.goto(f"{URL}/#/theme/run_t")
    page.locator(".run-progress").wait_for()
    return polls


def test_vanished_run_stops_polling(page):  # AC-45, AC-46
    polls = _running_card(page, [(200, manifest("running")), (404, {"detail": "Run not found"})])
    page.get_by_text("This run no longer exists.").wait_for(timeout=12_000)
    assert page.locator(".run-progress").count() == 0
    assert page.get_by_text("0/5").count() == 0
    seen = polls.count
    page.wait_for_timeout(12_000)
    assert polls.count == seen


def test_other_poll_error_keeps_polling(page):  # AC-116
    polls = _running_card(page, [(200, manifest("running")), (500, {"detail": "boom"})])
    page.get_by_text("Could not refresh: ").wait_for(timeout=12_000)
    seen = polls.count
    page.wait_for_timeout(12_000)
    assert polls.count > seen


def test_cancel_gives_feedback(page):  # AC-47
    _running_card(page, [(200, manifest("running"))])
    page.route("**/api/runs/run_t/cancel", lambda r: r.fulfill(json=manifest("running", cancel_requested=True)))
    page.get_by_role("button", name="Cancel run").click()
    page.get_by_text("Cancelling… the run stops after the item in progress.").wait_for()
    assert page.get_by_role("button", name="Cancel run").is_disabled()


def _position(page, step4):
    version = {"summary": "S", "paragraphs": [], "version": 1, "dossier_id": "d1", "note_version": 1, "created_by": "m",
               "created_at": "2026-11-11T09:00:00Z", "path": "model_draft"}
    standards = {"versions": [{"version": 1, "created_by": "m", "created_at": None, "position_version": 1,
                               "path": "model_draft", "standards": [], "schema": None}],
                 "activations": [], "active_version": 0, "active": None, "latest_check": None, "field_names": {}}
    page.route("**/api/me", lambda r: r.fulfill(json={"user_id": "u", "name": "ana", "role": "approver"}))
    page.route("**/api/dossiers/d1", lambda r: r.fulfill(json={"dossier_id": "d1", "name": "Grid", "steps": [
        {"number": 4, "title": "Find companies", "state": step4, "detail": "", "href": None}]}))
    page.route("**/api/dossiers/d1/research", lambda r: r.fulfill(json={"dossier_id": "d1", "approved_round": None, "rounds": []}))
    page.route("**/api/dossiers/d1/position", lambda r: r.fulfill(json={
        "versions": [version], "approvals": [{"version": 1, "approved_by": "a", "approved_at": "2026-11-11T09:00:00Z"}],
        "approved_version": 1}))
    page.route("**/api/dossiers/d1/standards", lambda r: r.fulfill(json=standards))
    page.goto(f"{URL}/#/themes/d1/position")
    return page.get_by_label("Standards").get_by_role("button", name="Approve", exact=True)


def test_approve_waits_for_step_4(page):  # AC-94
    approve = _position(page, "waiting")
    approve.wait_for()
    assert approve.is_disabled()
    page.get_by_text("Find companies first: finish step 4 of the dossier.").wait_for()
    assert page.get_by_role("link", name="Open the dossier").get_attribute("href") == "#/themes/d1"


def test_approve_after_step_4(page):  # AC-117
    approve = _position(page, "done")
    page.wait_for_function("() => [...document.querySelectorAll('button')].some(b => b.textContent === 'Approve' && !b.disabled)")
    assert approve.is_enabled()
