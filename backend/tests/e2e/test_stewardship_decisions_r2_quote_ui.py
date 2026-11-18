"""stewardship-decisions-round-2, area 2 in the browser: a found commitment's quote shows only when it is word for word
in its note; otherwise `Show the note` moves focus to the note (AC-10 to AC-14), with the suggestions list stubbed."""

import httpx

from tests.e2e import test_showcase_stewardship_side as side
from tests.e2e.test_showcase_stewardship_side import API, URL, _engagement_issue, pytestmark  # noqa: F401

page = side.page  # the shared browser fixture
QUOTE = "We will publish a transition plan by 2026."


def _open(page, summary, quote=QUOTE, known_note=True):
    company, issue_id = _engagement_issue()
    base = f"{API}/api/engagement/records/{company}"
    httpx.post(f"{base}/issues/{issue_id}/log-outreach-sent", json={"summary": summary}).raise_for_status()
    [issue] = [i for i in httpx.get(base).raise_for_status().json()["issues"] if i["issue_id"] == issue_id]
    entry_id = issue["correspondence"][-1]["entry_id"] if known_note else "act_unknown"
    found = {"suggestion_id": "sug_1", "kind": "new_commitment", "company_id": company, "engagement_id": issue_id,
             "activity_id": entry_id, "text": "Publish a transition plan", "quote": quote,
             "status": "pending", "created_at": "2026-11-15T00:00:00+00:00"}
    page.route("**/api/stewardship/evidence-suggestions*",
               lambda r: r.fulfill(json={"suggestions": [found] if "status=pending" in r.request.url else []}))
    page.goto(f"{URL}/#/engagement")
    page.locator("section.card", has_text=f"({company}) issues").locator(".issue-row").click()
    card = page.locator(".suggestion", has_text="Publish a transition plan")
    card.wait_for()
    return card, entry_id


def test_quote_shown_when_word_for_word(page):  # AC-10
    card, _ = _open(page, "Call notes: we will  publish a transition plan by 2026. Next call in May.")
    assert card.locator("blockquote").inner_text() == f'"{QUOTE}"'
    assert card.get_by_role("button", name="Show the note").count() == 0


def test_typographic_quotes_and_dashes_match(page):  # AC-11
    card, _ = _open(page, "They said we'll publish - by 2026.", quote="We’ll publish – by 2026")
    assert card.locator("blockquote").count() == 1


def test_no_quote_and_show_the_note_moves_focus(page):  # AC-12, AC-13
    card, entry_id = _open(page, "We shall publish a transition plan by 2026.")
    assert card.locator("blockquote").count() == 0
    card.get_by_role("button", name="Show the note").click()
    assert page.evaluate("document.activeElement.id") == f"note-{entry_id}"


def test_unknown_note_shows_no_quote_and_no_button(page):  # AC-14
    card, _ = _open(page, "anything", known_note=False)
    assert card.locator("blockquote").count() == 0
    assert card.get_by_role("button", name="Show the note").count() == 0
