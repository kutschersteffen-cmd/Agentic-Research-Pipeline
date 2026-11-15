"""commitment-loop-review-fixes in the browser: the suggestions error line (AC-13) and the found-commitment header
with an unknown note (AC-16), with the suggestions list stubbed."""

import httpx

from tests.e2e import test_showcase_stewardship_side as side
from tests.e2e.test_showcase_stewardship_side import API, URL, _engagement_issue, pytestmark  # noqa: F401

page = side.page  # the shared browser fixture


def _open(page, company):
    page.goto(f"{URL}/#/engagement")
    page.locator("section.card", has_text=f"({company}) issues").locator(".issue-row").click()
    page.get_by_role("heading", name="Commitments").wait_for()


def test_a_500_shows_suggestions_unavailable_and_no_check_button(page):  # AC-13
    company, issue_id = _engagement_issue()
    body = {"company_id": company, "issue_id": issue_id, "text": "Publish a transition plan", "target_date": "2027-03-31"}
    httpx.post(f"{API}/api/stewardship/tracking/commitments", json=body).raise_for_status()
    page.route("**/api/stewardship/evidence-suggestions*", lambda r: r.fulfill(status=500, json={"detail": "boom"}))
    _open(page, company)
    page.get_by_text("Suggestions unavailable: 500: boom").wait_for()  # the suggestions load has settled
    assert page.get_by_text("Suggestions unavailable: 500: boom").count() == 1
    assert page.get_by_role("button", name="Check against documents").count() == 0


def test_a_found_commitment_from_an_unknown_note_names_no_date(page):  # AC-16
    company, issue_id = _engagement_issue()
    found = {"suggestion_id": "sug_1", "kind": "new_commitment", "company_id": company, "engagement_id": issue_id,
             "activity_id": "act_unknown", "text": "Publish a transition plan", "quote": "We will publish a plan.",
             "status": "pending", "created_at": "2026-11-15T00:00:00+00:00"}

    def answer(route):
        pending = "status=pending" in route.request.url
        route.fulfill(json={"suggestions": [found] if pending else []})

    page.route("**/api/stewardship/evidence-suggestions*", answer)
    _open(page, company)
    card = page.locator(".suggestion", has_text="Publish a transition plan")
    assert card.locator("strong").inner_text() == "Argus found a commitment in a note"
