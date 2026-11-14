"""stewardship-commitment-loop PR 3 in the browser: the ballot banner (AC-94) and the dossier watch list (AC-109, AC-110),
with the named API routes stubbed."""

from tests.e2e import test_showcase_stewardship_side as side
from tests.e2e.test_showcase_stewardship_side import RUN_ID, URL, _engagement_issue, _run, _vote, pytestmark  # noqa: F401

page = side.page  # the shared browser fixture

FLAG = 'Objective overdue: "Set a 2030 science-based target" was due 2026-11-12.'


def test_watch_flag_banner_on_every_item_of_the_company(page):  # AC-94
    flag = {"item_kind": "objective", "item_id": "obj_1", "engagement_id": "iss_1", "kind": "overdue",
            "text": "Set a 2030 science-based target", "target_date": "2026-11-12", "since": "2026-11-12", "message": FLAG}
    b_vote = {**_vote(3), "proposal": {**_vote(3)["proposal"], "company_id": "BETA"}}
    ballots = [
        {"company_id": "ACME", "name": "Acme", "meeting_id": "m1", "meeting_date": "2026-12-01", "votes": [_vote(1), _vote(2)], "watch_flags": [flag]},
        {"company_id": "BETA", "name": "Beta", "meeting_id": "m2", "meeting_date": "2026-12-01", "votes": [b_vote], "watch_flags": []},
    ]
    page.route(f"**/api/voting/runs/{RUN_ID}/ballots", lambda r: r.fulfill(json={"ballots": ballots}))
    page.route(f"**/api/voting/runs/{RUN_ID}/review-queue", lambda r: r.fulfill(json={"pending": [], "decided": []}))
    page.route(f"**/api/voting/runs/{RUN_ID}/cast", lambda r: r.fulfill(json={"votes": []}))
    page.route(f"**/api/runs/{RUN_ID}", lambda r: r.fulfill(json=_run(company_count=2, done=2)))
    page.goto(f"{URL}/#/voting/{RUN_ID}")
    page.locator(".proposal-card").first.wait_for()
    assert page.locator(".banner-warning", has_text=FLAG).count() == 2
    assert page.locator(".proposal-card").count() == 3


def _dossier(company, issue_id, watch_list):
    return {"dossier_id": "d1", "company_id": company, "issue_id": issue_id, "generated_at": "2026-11-12T00:00:00+00:00",
            "summary": "s", "controversy_context": "c", "peer_benchmark_notes": "p", "engagement_history_summary": "",
            "recommended_contacts": ["IR"], "citations": [], "confidence": 0.9, "needs_review": False, "watch_list": watch_list}


def _draft(page, watch_list):
    company, issue_id = _engagement_issue()
    dossier = _dossier(company, issue_id, watch_list)
    page.route(f"**/issues/{issue_id}/dossier", lambda r: r.fulfill(json={"dossier": dossier, "needs_review": False}))
    page.goto(f"{URL}/#/engagement")
    page.locator("section.card", has_text=f"({company}) issues").locator(".issue-row").click()
    page.get_by_role("button", name="Draft dossier").click()
    page.get_by_role("heading", name="Watch list").wait_for()


def test_dossier_watch_list(page):  # AC-109, AC-110
    entries = [
        {"item_kind": "objective", "item_id": "obj_1", "text": "Set a 2030 science-based target", "proof_statement": None,
         "target_date": "2026-11-13", "status": "in_progress", "flag": "overdue", "evidence": []},
        {"item_kind": "topic", "item_id": "wtp_1", "text": "Has the company named a board climate committee?",
         "proof_statement": None, "target_date": None, "status": "open", "flag": None, "evidence": []},
    ]
    _draft(page, entries)
    rows = page.locator(".review-item .activity-row")
    assert rows.nth(0).inner_text().split("\n") == ["Objective: Set a 2030 science-based target", "due 2026-11-13", "overdue"]
    assert rows.nth(1).inner_text() == "Watch topic: Has the company named a board climate committee?"


def test_dossier_watch_list_empty(page):  # AC-110
    _draft(page, [])
    page.get_by_text("No open objectives, commitments or watch topics.").wait_for()
