"""One waiting count (docs/superpowers/specs/2026-11-15-waiting-count-design.md) against the running app."""

import pytest

from tests.e2e.test_ui_polish_1 import URL, _open, page  # noqa: F401  (page is a fixture)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]


def _waiting(pg, review, decisions, ballots):
    total = review + decisions + ballots
    pg.route("**/api/waiting", lambda r: r.fulfill(json={"review": review, "decisions": decisions, "ballots": ballots, "total": total}))


def test_badge_reads_waiting_not_runs(page):  # noqa: F811
    def runs(route):
        resp = route.fetch()
        body = resp.json()
        for r in body.get("runs", []):
            r["review_count"] = 999
        route.fulfill(response=resp, json=body)

    page.route("**/api/runs", runs)
    _waiting(page, 82, 15, 3)
    _open(page, "/#/stewardiq")
    badge = page.locator(".start-topbar .nav-count")
    assert badge.inner_text() == "100"
    assert badge.get_attribute("aria-label") == "100 waiting for a decision: 82 review items, 15 stewardship decisions, 3 ballots"


def test_review_queue_names_other_parts(page):  # noqa: F811
    _waiting(page, 0, 15, 3)
    _open(page, "/#/review")
    a = page.get_by_role("link", name="15 stewardship decisions also wait, in Steward Workflow →")
    b = page.get_by_role("link", name="3 ballots also wait, in Proxy Voting →")
    assert a.get_attribute("href") == "#/stewardship" and b.get_attribute("href") == "#/voting"


def test_review_queue_no_note(page):  # noqa: F811
    _waiting(page, 5, 0, 0)
    with page.expect_response("**/api/waiting"):
        _open(page, "/#/review")
    page.wait_for_timeout(300)  # the note renders on the next tick after the answer
    assert page.get_by_text("also wait").count() == 0


def test_failure_hides_badge_and_note(page):  # noqa: F811
    page.route("**/api/waiting", lambda r: r.fulfill(status=500, json={"detail": "boom"}))
    with page.expect_response("**/api/waiting"):
        _open(page, "/#/review")
    page.wait_for_timeout(300)  # let the rejected promise settle before checking nothing rendered
    assert page.locator(".start-topbar .nav-count").count() == 0
    assert page.get_by_text("also wait").count() == 0
