"""RFP project page against the running app, with its API stubbed by Playwright routing."""

import os
import time

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


def test_ac_40_document_source_and_priority(page):
    body = drafted("We held 512 engagement meetings in 2025.", None, [])
    q = body["questions"][0]
    q.update(base_entry_id=None, document_priority=2, sources=[
        {"kind": "document", "document_id": 4, "title": "Stewardship Statement 2025", "file": "ref_stmt.pdf", "priority": 2,
         "page": 2, "quote": "512 engagement meetings"}])
    card = open_card(page, body)
    for text in ("Uses documents (priority 2)", "Stewardship Statement 2025", "p. 2", "512 engagement meetings"):
        assert card.get_by_text(text).first.is_visible(), text


def test_screen_readers_hear_which_words_were_added_and_removed(page):  # UI review on #505, WCAG 1.3.1
    segments = [("Example AM is an", "kept"), ("independent", "removed"), ("asset", "added"), ("manager founded in 2004.", "kept")]
    card = open_card(page, drafted("Example AM is an asset manager founded in 2004.", 80, segments))
    assert card.locator("del").text_content() == "removed: independent"
    assert card.locator("ins").text_content() == "added: asset"
    assert card.get_by_text("removed:").evaluate("e => getComputedStyle(e).position") == "absolute"  # not shown on screen


def test_approved_answer_shows_no_change_line(page):  # spec §6: drafted or edited answers only
    card = open_card(page, drafted(FIRM_A, 100, [(FIRM_A, "kept")], status="approved"))
    assert card.get_by_text("Approved answer, unchanged").count() == 0
    assert card.get_by_text("From approved answers only").count() == 0


def test_edited_answer_shows_the_change_line_but_not_its_origin(page):  # spec §6: origin on drafted answers only
    card = open_card(page, drafted(FIRM_A, 100, [(FIRM_A, "kept")], status="edited"))
    assert card.get_by_text("Approved answer, unchanged").is_visible()
    assert card.get_by_text("From approved answers only").count() == 0


# --- UI review on #545: the reference-documents form and Retire --------------------------------

def documents_page(page, refuse_retire=False, posts=None):
    posts = [] if posts is None else posts
    doc = {"id": 4, "title": "Stewardship Statement 2025", "filename": "ref_stmt.docx", "document_date": "2025-12-31",
           "review_by": "2026-12-31", "priority": 1, "status": "active", "uploaded_by": "dev", "pages": None}

    def listing(route):
        if route.request.method == "POST":  # every upload is refused, slowly enough for a second click to land
            posts.append(1)
            time.sleep(0.5)
            route.fulfill(status=400, json={"detail": "scan.pdf has no text layer; upload the original document."})
        else:
            route.fulfill(json=[doc])

    def retire(route):
        if refuse_retire:
            route.fulfill(status=404, json={"detail": "Reference document not found"})
            return
        doc["status"] = "retired"
        route.fulfill(json=doc)

    page.route("**/api/rfp/documents", listing)
    page.route("**/api/rfp/documents/4/retire", retire)
    page.goto(f"{URL}/#/rfp")
    section = page.locator("section", has=page.get_by_role("heading", name="Reference documents"))
    section.get_by_role("cell", name="Stewardship Statement 2025").wait_for()
    return section


def test_upload_form_has_visible_labels(page):  # WCAG 3.3.2
    section = documents_page(page)
    for label in ("File", "Title", "Document date", "Priority (1 = first)", "Replaces"):
        assert section.get_by_label(label).first.is_visible(), label
        assert section.locator("label", has_text=label).first.is_visible(), label


def test_focus_moves_to_the_heading_after_retire(page):  # WCAG 2.4.3
    section = documents_page(page)
    section.get_by_role("button", name="Retire").focus()
    page.keyboard.press("Enter")
    section.get_by_role("cell", name="retired").wait_for()
    assert page.evaluate("document.activeElement.textContent") == "Reference documents"


def test_focus_stays_on_upload_after_a_refused_upload(page):  # UI review on #556, WCAG 2.4.3
    section = documents_page(page)
    page.set_input_files("#rfp-document-file", files=[{"name": "scan.pdf", "mimeType": "application/pdf", "buffer": b"%PDF"}])
    page.fill("#rfp-document-title", "Scan")
    page.fill("#rfp-document-date", "2025-12-31")
    section.get_by_role("button", name="Upload document").focus()
    page.keyboard.press("Enter")
    section.get_by_role("alert").wait_for()
    assert page.evaluate("document.activeElement.textContent") == "Upload document"


def test_focus_stays_on_retire_after_a_refused_retire(page):  # UI review on #556, WCAG 2.4.3
    section = documents_page(page, refuse_retire=True)
    section.get_by_role("button", name="Retire").focus()
    page.keyboard.press("Enter")
    section.get_by_role("alert").wait_for()
    assert page.evaluate("document.activeElement.textContent") == "Retire"


def test_a_double_click_on_upload_sends_one_request(page):  # code re-review on #556: the busy guard is a ref now
    posts = []
    section = documents_page(page, posts=posts)
    page.set_input_files("#rfp-document-file", files=[{"name": "scan.pdf", "mimeType": "application/pdf", "buffer": b"%PDF"}])
    page.fill("#rfp-document-title", "Scan")
    page.fill("#rfp-document-date", "2025-12-31")
    section.get_by_role("button", name="Upload document").dblclick()
    section.get_by_role("alert").wait_for()
    page.wait_for_timeout(700)  # a second request, had one been sent, would have arrived by now
    assert len(posts) == 1
