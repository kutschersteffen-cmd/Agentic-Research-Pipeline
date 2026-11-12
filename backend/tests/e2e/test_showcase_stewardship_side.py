"""showcase-stewardship-fixes PR B, the "unit (browser)" rows: the running app with the named API routes stubbed."""

import json
import os
import re
import uuid

import httpx
import pytest

from arp.config import Settings

URL = os.environ.get("ARP_E2E_URL")
API = os.environ.get("ARP_E2E_API_URL", "http://127.0.0.1:8000")  # the stack's API (e2e_stack.sh)
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

ANA = {"user_id": "u_ana", "name": "Ana", "role": "approver"}


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(10_000)
        page.route("**/api/me", lambda r: r.fulfill(json=ANA))
        page.add_init_script("localStorage.setItem('arp.reviewer', 'Ana')")  # the voting reviewer is typed per device
        yield page
        browser.close()


# --- Engagement panel: the same summary twice, letter placeholders (AC-101, AC-155) ---


def _engagement_issue() -> tuple[str, str]:
    company = f"E2E{uuid.uuid4().hex[:6].upper()}"
    httpx.post(f"{API}/api/engagement/records", json={"company_id": company, "name": "Acme Panel"}).raise_for_status()
    res = httpx.post(f"{API}/api/engagement/records/{company}/issues?name=Acme%20Panel", json={"theme": "climate"})
    return company, res.raise_for_status().json()["issue_id"]


def test_outreach_twice_sends_the_same_summary_and_placeholders_show(page):  # AC-101, AC-155
    company, issue_id = _engagement_issue()
    dossier = {"dossier_id": "d1", "company_id": company, "issue_id": issue_id, "generated_at": "2026-11-12T00:00:00+00:00",
               "summary": "s", "controversy_context": "c", "peer_benchmark_notes": "p", "engagement_history_summary": "",
               "recommended_contacts": ["IR"], "citations": [], "confidence": 0.9, "needs_review": False}
    letter = {"subject": "Engagement request from [Fund name]", "body": "Dear IR", "recommended_recipient": "IR",
              "citations": [], "placeholders": ["[Fund name]"]}
    page.route(f"**/issues/{issue_id}/dossier", lambda r: r.fulfill(json={"dossier": dossier, "needs_review": False}))
    page.route(f"**/issues/{issue_id}/outreach-letter", lambda r: r.fulfill(json=letter))
    summaries = []

    def log(route):
        summaries.append(json.loads(route.request.post_data)["summary"])
        route.continue_()

    page.route(f"**/issues/{issue_id}/log-outreach-sent", log)
    page.goto(f"{URL}/#/engagement")
    page.locator("section.card", has_text=f"({company}) issues").locator(".issue-row").click()
    page.get_by_role("button", name="Draft dossier").click()
    page.get_by_role("button", name="Draft outreach letter").click()
    page.get_by_text("Fill in before sending: [Fund name]").wait_for()
    button = page.get_by_role("button", name="Log outreach sent")
    for n in (1, 2):
        button.click()
        page.wait_for_timeout(500)
        assert len(summaries) == n
    assert summaries[0] == summaries[1]


def test_scan_says_which_signals_were_skipped(page):  # AC-111
    page.route("**/api/engagement/trigger-scan", lambda r: r.fulfill(
        json={"events": [], "unlisted_signals": {"count": 3, "company_ids": ["C2", "C3"]}}))
    page.goto(f"{URL}/#/engagement")
    form = page.locator("section", has=page.get_by_role("button", name="Run scan"))
    form.get_by_placeholder("e.g. AAPL").nth(0).fill("C1")  # the company row, then the signal row
    form.get_by_label("Company name").fill("Acme")
    form.get_by_placeholder("e.g. AAPL").nth(1).fill("C2")
    form.get_by_label("Theme").first.fill("climate")
    page.get_by_role("button", name="Run scan").click()
    page.get_by_text("3 signals skipped: their companies are not in the list (C2, C3).").wait_for()


# --- Proxy Voting (AC-116..122, 129..133, 137, 170, 171) ---

RUN_ID = "voting_e2e1"


def _run(status="completed", done=5, company_count=5):
    return {"run_id": RUN_ID, "run_type": "proxy_voting", "created_at": "2026-11-12T09:00:00+00:00",
            "updated_at": "2026-11-12T09:05:00+00:00", "status": status, "params": {}, "company_count": company_count,
            "completed_count": done, "failed_count": 0, "review_count": 0, "input_tokens": 0, "output_tokens": 0,
            "estimated_cost_usd": 0.0, "error": None}


def _vote(n, ptype="capital_action", text="Routine item.", rule="rule_routine_management_proposal", confidence=1.0,
          flag=False, confirmation=None):
    return {
        "vote_record_id": f"v{n}", "run_id": RUN_ID,
        "proposal": {"proposal_id": f"p{n}", "company_id": "ACME", "meeting_id": "m1", "meeting_date": "2026-12-01",
                     "proposal_number": str(n), "type": ptype, "sponsor": "management", "resolution_text": text,
                     "management_recommendation": "for", "supporting_data": {}, "citations": [], "confidence": 0.9},
        "policy_recommendation": {"vote": "for", "rationale": "r", "policy_rule_id": rule, "confidence": confidence,
                                  "engagement_alignment_flag": flag, "engagement_alignment_note": None},
        "cast_confirmation": confirmation and {"platform": "manual", "cast_at": "2026-11-12T10:00:00+00:00",
                                               "confirmation_id": confirmation, "status": "confirmed"},
    }


def _decided(votes, decision="approve"):
    return [{"item": {"item_key": f"ACME:{v['proposal']['proposal_number']}"},
             "decision": {"item_key": f"ACME:{v['proposal']['proposal_number']}", "decision": decision, "reviewer": "Ana",
                          "decided_at": "2026-11-12T09:30:00+00:00", "edited_value": None}} for v in votes]


def open_voting(page, votes, decided=(), cast=(), run=None, on_cast=None, on_review=None):
    """`cast` is read on each GET /cast, so a test can fill it from its POST handler."""
    ballots = [{"company_id": "ACME", "name": "Acme", "meeting_date": "2026-12-01", "votes": votes}] if votes else []
    page.route(f"**/api/voting/runs/{RUN_ID}/ballots", lambda r: r.fulfill(json={"ballots": ballots}))
    page.route(f"**/api/voting/runs/{RUN_ID}/review-queue", lambda r: r.fulfill(json={"pending": [], "decided": list(decided)}))

    def cast_route(route):
        if route.request.method == "POST" and on_cast:
            on_cast(route)
        else:
            route.fulfill(json={"votes": list(cast)})

    page.route(f"**/api/voting/runs/{RUN_ID}/cast", cast_route)
    page.route(f"**/api/voting/runs/{RUN_ID}/review", on_review or (lambda r: r.fulfill(json={"status": "recorded"})))
    page.route(f"**/api/runs/{RUN_ID}", lambda r: r.fulfill(json=run or _run()))
    page.route(re.compile(r".*/api/runs/" + RUN_ID + r"/progress.*"), lambda r: r.fulfill(json={}))
    page.goto(f"{URL}/#/voting/{RUN_ID}")


FORBIDDEN = ["this sends", "confirmation id", "confirmation conf_", "by the platform", "submitted", "sent to"]


def assert_no_send_wording(page):
    text = page.locator("main").inner_text().lower().replace("nothing is sent to a ballot platform from here.", "")
    assert not [w for w in FORBIDDEN if w in text], text


def test_cast_dialog_says_what_is_recorded(page):  # AC-116, AC-122
    votes = [_vote(n) for n in range(1, 6)]
    open_voting(page, votes, decided=_decided(votes))
    page.get_by_role("button", name="Cast 5 decided votes…").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_text("This records 5 votes").wait_for()
    assert dialog.locator("p").first.inner_text() == (
        "This records 5 votes as voting instructions, one file per vote, to be entered on the ballot platform by hand. "
        "Nothing is sent to a ballot platform from here. Recorded votes cannot be recalled from here.")
    assert_no_send_wording(page)


def test_cast_dialog_for_one_vote(page):  # AC-117
    votes = [_vote(1)]
    open_voting(page, votes, decided=_decided(votes))
    page.get_by_role("button", name="Cast 1 decided vote…").click()
    assert page.get_by_role("dialog").locator("p").first.inner_text() == (
        "This records 1 vote as a voting instruction, in its own file, to be entered on the ballot platform by hand. "
        "Nothing is sent to a ballot platform from here. Recorded votes cannot be recalled from here.")


def test_recorded_banner_and_instruction_ref(page):  # AC-118, AC-119, AC-122
    votes = [_vote(n) for n in range(1, 6)]
    cast = []  # what GET /cast answers; filled by the POST

    def on_cast(route):
        cast.extend(_vote(n, confirmation=f"conf_{n}") for n in range(1, 6))
        route.fulfill(json={"cast_count": 5, "votes": cast})

    open_voting(page, votes, decided=_decided(votes), cast=cast, on_cast=on_cast)
    page.get_by_role("button", name="Cast 5 decided votes…").click()
    page.get_by_role("dialog").get_by_role("button", name="Cast 5 votes").click()
    banner = page.locator(".banner-success").first
    banner.wait_for()
    text = banner.inner_text()
    assert text.startswith("5 votes recorded as voting instructions by Ana at")
    assert text.endswith("The instruction reference is shown on each proposal below.")
    page.get_by_text("Recorded · instruction ref conf_1").wait_for()
    assert_no_send_wording(page)


def test_missing_co_sign_warning(page):  # AC-120
    votes = [_vote(1, flag=True), _vote(2, flag=True)]
    open_voting(page, votes, decided=_decided(votes))
    page.get_by_role("button", name="Cast 2 decided votes…").click()
    page.get_by_text("2 flagged votes have no co-sign and will be refused when the votes are recorded.").wait_for()
    assert_no_send_wording(page)


def test_failed_cast_says_nothing_was_recorded(page):  # AC-121, AC-122
    votes = [_vote(1)]
    open_voting(page, votes, decided=_decided(votes), on_cast=lambda r: r.fulfill(status=400, json={"detail": "X"}))
    page.get_by_role("button", name="Cast 1 decided vote…").click()
    page.get_by_role("dialog").get_by_role("button", name="Cast 1 vote").click()
    page.get_by_text("Recording the votes failed: X. Nothing was recorded; try again.").wait_for()
    assert_no_send_wording(page)


def test_routine_sweep_leaves_out_say_on_pay_model_judged_and_redomiciliation(page):  # AC-129
    votes = [
        _vote(1, ptype="say_on_pay", text="Approve executive pay"),
        _vote(2, ptype="director_election", text="Elect A", rule=None, confidence=0.95),
        _vote(3),
        _vote(4, ptype="other", text="Approve the redomiciliation of the Company to Delaware"),
    ]
    posted = []

    def review(route):
        posted.append(json.loads(route.request.post_data))
        route.fulfill(json={"status": "recorded"})

    open_voting(page, votes, on_review=review)
    page.get_by_role("button", name="Approve 1 routine…").click()
    page.get_by_role("button", name="Approve 1", exact=True).click()
    page.wait_for_timeout(500)
    assert [p["item_key"] for p in posted] == ["ACME:3"]


@pytest.mark.parametrize(
    ("status", "done", "text"),
    [
        ("running", 2, "This voting run is still in progress (2 of 5 companies done). Ballots appear here as they are ready."),
        ("pending", 0, "This voting run is still in progress (0 of 5 companies done). Ballots appear here as they are ready."),
        ("failed", 0, "This voting run stopped before any ballot was ready (status: failed). Run History shows why."),
        ("cancelled", 0, "This voting run stopped before any ballot was ready (status: cancelled). Run History shows why."),
        ("completed", 5, "No ballots in this run yet: none of its companies has a proxy statement for an upcoming meeting. "
                         "Start a new voting run once one is filed."),
    ],
)
def test_empty_ballot_list_by_run_status(page, status, done, text):  # AC-130..133
    open_voting(page, [], run=_run(status, done))
    page.get_by_text(text).wait_for()
    if status != "completed":
        assert page.get_by_text("No ballots in this run yet").count() == 0


def test_override_needs_a_reason(page):  # AC-137
    open_voting(page, [_vote(1, ptype="say_on_pay", text="Approve executive pay")])
    page.get_by_role("button", name="Override…").click()
    field = page.get_by_label("Reason for the override (required)")
    button = page.get_by_role("button", name="Record override")
    assert field.is_visible() and button.is_disabled()
    field.fill("Board lacks independence")
    assert button.is_enabled()


def test_announcer_is_cleared_on_another_screen(page):  # AC-170, AC-171
    open_voting(page, [_vote(1)])
    page.get_by_role("button", name="Approve: vote for").click()
    page.wait_for_function("() => document.getElementById('announcer').textContent.includes('approved')")
    assert page.locator("#announcer").text_content() == "Proposal 1 for Acme approved."
    page.goto(f"{URL}/#/engagement")
    page.get_by_role("heading", name="Engagement", exact=True).wait_for()
    assert page.locator("#announcer").text_content() == ""


# --- Steward Workflow: chips and four-eyes (AC-141, AC-144) ---


def test_client_program_marks_placeholder_scores(page):  # AC-141
    name = f"Client {uuid.uuid4().hex[:4]}"
    httpx.post(f"{API}/api/stewardship/streams", json={"name": name}).raise_for_status()
    note = "CLTI scores are placeholders, not an assessment of these companies. Do not share this as a view on them."

    def program(route):  # the sample benchmark has no score note; portfolio holdings do
        if route.request.method != "GET":
            return route.fallback()
        body = route.fetch().json()
        body["simulation"]["score_note"] = note
        route.fulfill(json=body)

    page.route(re.compile(r".*/api/stewardship/streams/[^/]+/program$"), program)
    page.goto(f"{URL}/#/stewardship/program")
    page.get_by_label("Client stream").select_option(label=name)
    page.locator(".warning-banner", has_text="CLTI scores are placeholders").wait_for()
    banner = page.locator(".warning-banner", has_text="CLTI scores are placeholders")
    assert banner.locator(".chip-sample").count() == 1 and banner.inner_text().startswith("Sample data")
    tile = lambda label: page.locator(".metric-tile", has_text=label)  # noqa: E731
    assert tile("Weighted CLTI").locator(".chip-sample").count() == 1
    assert tile("Active share").locator(".chip-sample").count() == 0


def test_outreach_draft_by_the_signed_in_author_says_a_second_person_is_needed(page):  # AC-144
    item = {"kind": "outreach", "draft_id": "dr1", "company": "Acme", "theme": "climate", "type": "letter",
            "interaction_type": "dialogue", "proposed_interaction_type": "dialogue", "proposed_because": "x",
            "text": "Dear board", "style_flags": [], "authors": ["Ana"]}

    def flow(route):
        body = route.fetch().json()
        for stage in body["stages"]:
            if stage["id"] == "checkpoint":
                stage["decisions"] = [item, *stage.get("decisions", [])]
        route.fulfill(json=body)

    page.route("**/api/stewardship/streams/house/flow", flow)
    page.goto(f"{URL}/#/stewardship/checkpoint")
    button = page.get_by_role("button", name="Approve for sending")
    button.wait_for()
    assert button.is_disabled()
    page.get_by_text(
        "A second person is needed: this draft was written by Ana, and someone who did not write it approves it."
    ).wait_for()


# --- RFP four-eyes (AC-145) ---


def test_rfp_answer_edited_last_by_the_approver_says_a_second_person_is_needed(page):  # AC-145
    question = {"id": 7, "location": "Q1", "answer_location": "B2", "question": "Do you vote?", "answer": "Yes",
                "status": "draft", "flags": [], "assignee": None, "last_editor": "u_ana", "sources": []}
    project = {"id": 1, "investor": "Nordic Pension Fund", "due_date": None, "filename": "rfp_in.xlsx", "run_status": "done",
               "not_located": 0, "question_count": 1, "approved_count": 0, "questions": [question]}
    page.route("**/api/rfp/projects/1", lambda r: r.fulfill(json=project))
    page.goto(f"{URL}/#/rfp/1")
    page.get_by_text("A second person is needed: you edited this answer last, and another approver must approve it.").wait_for()
    assert page.get_by_role("button", name="Approve", exact=True).count() == 0
