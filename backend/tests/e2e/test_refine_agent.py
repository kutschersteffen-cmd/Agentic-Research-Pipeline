"""Refine threads on the Agent screen (spec refine-chat-design, amendment 2026-11-22) against the running app, with the
Refine API stubbed by Playwright routing: picker, empty thread, composer, a turn from `Working…` to its result lines, the
`Document` stage tab, and the `Mode` group coming back on another thread."""

import json
import os

import pytest

from arp.config import Settings

URL = os.environ.get("ARP_E2E_URL")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

R = "rpt_r"
DOCS = [{"kind": "rfp", "doc_id": "7", "title": "RFP: Nordic Pension Fund"}, {"kind": "deck", "doc_id": R, "title": "Deck: Climate review"}]
SLIDES = "".join(f'<section class="slide" data-slide="{i}"><h1 data-slide="{i}" data-slot="headline">S{i + 1}</h1></section>'
                 for i in range(4))
HTML = f"<html><head></head><body>{SLIDES}</body></html>"
MANIFEST = {"report_id": R, "created_at": "2026-11-22T10:00:00Z", "updated_at": "2026-11-22T10:00:00Z", "status": "completed",
            "title": "Climate review", "output_format": "house_deck", "input_tokens": 0, "output_tokens": 0, "output_files": [],
            "has_deck": True, "deck_edited_since_render": False}


def turn(status, **kw):
    return {"turn_id": 1, "user_id": "dev", "message": "make slide 2 a column chart", "reply": None, "status": status, "done": 0,
            "total": 0, "changed": [], "not_changed": [], "check_figures": [], "error": None,
            "created_at": "2026-11-22T10:00:00Z", **kw}


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(10_000)
        yield page
        browser.close()


@pytest.fixture
def api(page):
    """The Refine routes of one deck R: its turns list starts empty; a posted turn runs for two reads, then is done."""
    state = {"turns": [], "reads": 0}

    def json_route(body, status=200):
        return lambda route: route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

    def turns(route):
        if route.request.method == "POST":
            state["turns"] = [turn("running")]
            return route.fulfill(status=202, content_type="application/json", body=json.dumps({"turn_id": 1}))
        route.fulfill(content_type="application/json", body=json.dumps(state["turns"]))

    def one_turn(route):
        state["reads"] += 1
        done = state["reads"] > 2
        if done:
            state["turns"] = [turn("done", reply="Slide 2 is now a column chart.", changed=[2])]
        body = {"id": 1, "status": "done" if done else "running", "reply": "Slide 2 is now a column chart." if done else "",
                "done": 0, "total": 0, "changed": [2] if done else [], "not_changed": [], "check_figures": [], "error": None}
        route.fulfill(content_type="application/json", body=json.dumps(body))

    page.route("**/api/refine/threads", json_route([]))
    page.route("**/api/refine/documents", json_route(DOCS))
    page.route(f"**/api/refine/deck/{R}/turns", turns)
    page.route("**/api/refine/turns/1", one_turn)
    page.route(f"**/api/reports/{R}/deck/html", lambda route: route.fulfill(content_type="text/html", body=HTML))
    page.route(f"**/api/reports/{R}", json_route(MANIFEST))
    return state


def test_picker_opens_an_empty_deck_thread(page, api):  # AC-62, AC-62b, AC-62c, AC-62d, AC-74 (stubbed API)
    page.goto(f"{URL}/#/agent")
    page.get_by_role("button", name="Refine a document").click()
    page.wait_for_url("**/#/agent/refine")
    assert page.get_by_role("list", name="RFP responses").get_by_role("link").all_inner_texts() == ["RFP: Nordic Pension Fund"]
    assert page.get_by_role("list", name="Decks").get_by_role("link").all_inner_texts() == ["Deck: Climate review"]
    page.get_by_role("link", name="Deck: Climate review").click()
    page.wait_for_url(f"**/#/agent/refine/deck/{R}")
    page.get_by_text("No changes yet. Type an instruction below.").wait_for()
    stage = page.locator("aside.agent-stage")
    assert stage.get_by_role("tab").all_inner_texts() == ["Document"]
    stage.get_by_role("button", name="Slide 4").wait_for()
    assert stage.locator(".refine-thumb").count() == 4
    assert page.get_by_role("group", name="Mode").count() == 0
    assert page.get_by_label("Instruction").is_visible()
    assert page.get_by_role("button", name="Refine", exact=True).is_visible()


def test_a_turn_runs_then_shows_its_result(page, api):  # AC-74c, AC-66-style lines, AC-74b (stubbed API)
    page.goto(f"{URL}/#/agent")
    page.get_by_role("group", name="Mode").get_by_role("button", name="Ask").wait_for()
    assert page.get_by_role("group", name="Mode").get_by_role("button", name="Ask").get_attribute("aria-pressed") == "true"
    page.goto(f"{URL}/#/agent/refine/deck/{R}")
    box = page.get_by_label("Instruction")
    page.get_by_text("No changes yet. Type an instruction below.").wait_for()
    box.fill("make slide 2 a column chart")
    box.press("Enter")
    page.get_by_role("list", name="Turns").get_by_text("Working…").wait_for()
    assert box.is_disabled()
    assert page.get_by_role("button", name="Refining…").is_disabled()
    page.get_by_text("Changed: Slide 2").wait_for()
    assert page.get_by_role("list", name="Turns").get_by_text("dev").is_visible()
    page.locator("aside.agent-stage").get_by_role("button", name="Slide 2, changed").wait_for()
    assert box.is_enabled()
    page.goto(f"{URL}/#/agent")
    assert page.get_by_role("group", name="Mode").get_by_role("button", name="Ask").get_attribute("aria-pressed") == "true"


def test_a_refused_turn_shows_its_detail(page, api):  # spec: any response other than 202 shows its detail
    page.route(f"**/api/refine/deck/{R}/turns", lambda route: route.fulfill(
        status=409, content_type="application/json", body=json.dumps({"detail": "A change is already running on this document."}))
        if route.request.method == "POST" else route.fulfill(content_type="application/json", body="[]"))
    page.goto(f"{URL}/#/agent/refine/deck/{R}")
    page.get_by_text("No changes yet. Type an instruction below.").wait_for()
    box = page.get_by_label("Instruction")
    box.fill("shorter")
    box.press("Enter")
    page.locator("form.agent-composer").get_by_text("A change is already running on this document.").wait_for()
    assert box.input_value() == "shorter"


def test_a_failed_first_load_is_tried_again(page, api):  # code review #668 finding 1
    calls = {"n": 0}

    def turns(route):
        calls["n"] += 1
        if calls["n"] <= 2:  # both reads on open (mount and the poll's first tick) fail, so only the 3 s retry can load it
            return route.fulfill(status=502, content_type="application/json", body=json.dumps({"detail": "Bad gateway"}))
        route.fulfill(content_type="application/json", body="[]")

    page.route(f"**/api/refine/deck/{R}/turns", turns)
    page.goto(f"{URL}/#/agent/refine/deck/{R}")
    page.get_by_text("No changes yet. Type an instruction below.").wait_for()  # the next poll loads it
    assert page.get_by_label("Instruction").is_enabled()
    assert page.get_by_text("Bad gateway").count() == 0


def test_a_viewer_reads_the_deck_without_export_or_undo(page, api):  # D3, AC-71; code review #668 finding 2
    page.route("**/api/me", lambda r: r.fulfill(json={"user_id": "vic", "name": "vic", "role": "viewer"}))
    page.route(f"**/api/reports/{R}", lambda r: r.fulfill(json={**MANIFEST, "deck_edited_since_render": True}))
    page.goto(f"{URL}/#/agent/refine/deck/{R}")
    stage = page.locator("aside.agent-stage")
    stage.get_by_text("Preview changed since last export").wait_for()
    page.get_by_text("No changes yet.", exact=True).wait_for()
    assert stage.get_by_role("button", name="Export .pptx").count() == 0
    assert stage.get_by_role("button", name="Undo last turn").count() == 0
    assert page.get_by_label("Instruction").count() == 0


def test_a_turn_that_vanishes_does_not_leave_the_thread_working(page, api):  # code review #668 round 2 finding 1
    """Another person's undo shows in the list as a `running` lock row that is deleted when the undo ends; its turn read
    is 404 from then on. The screen reads the list again instead of waiting on that turn forever."""
    calls = {"n": 0}
    lock = turn("running", turn_id=999, user_id="anna", message="undo")

    def turns(route):
        calls["n"] += 1
        route.fulfill(content_type="application/json", body=json.dumps([lock] if calls["n"] == 3 else []))

    page.route(f"**/api/refine/deck/{R}/turns", turns)
    page.route("**/api/refine/turns/999", lambda r: r.fulfill(status=404, content_type="application/json",
                                                             body=json.dumps({"detail": "Turn not found"})))
    page.goto(f"{URL}/#/agent/refine/deck/{R}")
    page.get_by_role("list", name="Turns").get_by_text("Working…").wait_for()  # the lock row, on the third read
    page.get_by_text("No changes yet. Type an instruction below.").wait_for()
    assert page.get_by_label("Instruction").is_enabled()
    assert page.locator("aside.agent-stage").get_by_role("button", name="Undo last turn").is_enabled()
