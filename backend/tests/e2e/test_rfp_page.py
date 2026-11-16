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


# --- rfp-approved-answers-first-design: what changed against the approved answer ------------------

FIRM_Q, FIRM_A = "Describe your firm.", "Example AM is an independent manager founded in 2004."


def drafted(answer, kept_share, segments, status="drafted"):
    q = {"id": 7, "location": "RFP!A1", "answer_location": "RFP!B1", "question": "Please describe your firm.",
         "answer": answer, "status": status, "flags": [], "assignee": None, "last_editor": None,
         "sources": [{"kind": "entry", "entry_id": 3, "entry_question": FIRM_Q, "quote": FIRM_A, "source": "lib_past.xlsx",
                      "file": "lib_past.xlsx", "location": "Responses!B2", "written_by": None}],
         "document_priority": 0, "base_entry_id": 3, "kept_share": kept_share,
         "segments": [{"text": t, "change": c} for t, c in segments]}
    return project("done") | {"question_count": 1, "questions": [q]}


def open_card(page, body):
    page.route("**/api/rfp/projects/1", lambda route: route.fulfill(json=body))
    page.goto(f"{URL}/#/rfp/1")
    card = page.get_by_role("region", name="Question RFP!A1")
    card.wait_for()
    return card


ASSET_SEGMENTS = [("Example AM is an independent", "kept"), ("asset", "added"), ("manager founded in 2004.", "kept")]


def test_ac_12_changed_answer_shows_share_and_marks(page):
    card = open_card(page, drafted("Example AM is an independent asset manager founded in 2004.", 90, ASSET_SEGMENTS))
    for text in ("90% unchanged from the approved answer", FIRM_Q, "From approved answers only"):
        assert card.get_by_text(text).first.is_visible(), text
    assert card.locator("ins", has_text="asset").count() == 1
    assert card.locator("ins", has_text="Example").count() == 0 and card.locator("del", has_text="Example").count() == 0


def test_ac_13_unchanged_answer(page):
    card = open_card(page, drafted(FIRM_A, 100, [(FIRM_A, "kept")]))
    assert card.get_by_text("Approved answer, unchanged").is_visible()


def test_ac_46_removed_word_is_struck(page):
    segments = [("Example AM is an", "kept"), ("independent", "removed"), ("manager founded in 2004.", "kept")]
    card = open_card(page, drafted("Example AM is an manager founded in 2004.", 89, segments, status="edited"))
    assert card.get_by_text("89% unchanged from the approved answer").is_visible()
    assert card.locator("del", has_text="independent").count() == 1
    assert card.get_by_text("Approved answer, unchanged").count() == 0


def test_ac_56_full_share_with_an_added_word_is_not_unchanged(page):
    segments = [(" ".join(["w"] * 199), "kept"), ("new", "added")]  # 199 of 200 rounds to 100
    card = open_card(page, drafted(" ".join(["w"] * 199) + " new", 100, segments))
    assert card.get_by_text("100% unchanged from the approved answer").is_visible()
    assert card.get_by_text("Approved answer, unchanged").count() == 0
