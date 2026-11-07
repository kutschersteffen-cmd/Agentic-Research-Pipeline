"""Authority-taxonomy screens against the running app, with the API stubbed by Playwright routing."""

import json
import os

import pytest

from arp.config import Settings

URL = os.environ.get("ARP_E2E_URL")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]
API = "**/api/authority-taxonomy/**"
CHECKLIST = ["theme_description", "activities", "boundaries", "technologies", "definitions", "sector_codes", "value_chain", "thresholds"]
SRC = "https://example.org/eu-hydrogen"


def cite(quote="Electrolysers split water"):
    return {"quote": quote, "source_url": SRC, "location": "p. 4"}


def draft():
    activity = {
        "activity_id": "a1", "name": "Electrolysis", "in_scope_description": "in", "out_of_scope_description": "out",
        "value_chain_role": "core", "criteria": [{"text": "Crit one", "citations": [cite("Crit quote")]}],
        "seed_keywords": ["electrolyser"], "sector_codes": [{"system": "ISIC", "code": "2011", "origin": "exiobase"}],
        "citations": [cite()], "out_of_scope_citations": [],
    }
    return {
        "theme_id": "t", "name": "Hydrogen", "description": "Desc", "scope": "S1", "kpis": [],
        "technologies": [{"name": "PEM", "citations": [cite("PEM quote")]}],
        "definitions": [{"term": "Green", "text": "Made with renewables", "citations": [cite("Green quote")]}],
        "activities": [activity, {**activity, "activity_id": "a2", "name": "Storage"}],
        "thresholds": [{"text": "3 kg CO2e/kg H2", "citations": [cite("Threshold quote")]}],
        "checklist_report": {SRC: {k: ("found" if k in ("activities", "thresholds") else "not_in_source") for k in CHECKLIST}},
    }


def candidates():
    base = {"source_type": "regulatory_taxonomy", "summary": "Sum", "reason": "Why", "covers": [], "from_library": False}
    return [
        {**base, "url": SRC, "title": "EU Taxonomy hydrogen", "fetchable": True, "from_library": True, "covers": ["activities", "thresholds"]},
        {**base, "url": "https://example.org/blocked", "title": "Blocked report", "fetchable": False},
    ]


def run(stage, **kw):
    return {"run_id": "r1", "stage": stage, "theme_name": "Hydrogen", "theme_key": "hydrogen", "scope": "S1", "guidance": "G1",
            "value_chain": True, "candidates": [], "draft": None, "notes": "N", "taxonomy_id": None, "error": None, "selection": None,
            "step_started_at": None, **kw}


class Api:
    """Stubbed API: `state` is what GET answers; `calls` records (method, path, body)."""

    def __init__(self, page, state):
        self.state, self.calls, self.status = state, [], {}
        self.on_get = None
        page.route(API, self.handle)

    def handle(self, route):
        req = route.request
        path = req.url.split("/api/authority-taxonomy")[1]
        body = req.post_data_json if req.method in ("POST", "PUT") and "multipart" not in (req.header_value("content-type") or "") else None
        self.calls.append((req.method, path, body))
        key = f"{req.method} {path}"
        if key in self.status:
            code, payload = self.status[key]
            return route.fulfill(status=code, json=payload)
        if req.method == "GET":
            if self.on_get:
                self.on_get()
            return route.fulfill(json=self.state)
        if path == "/runs":
            return route.fulfill(status=201, json={"id": "r1", "stage": "discovering"})
        if path == "/uploads":
            return route.fulfill(json={"path": "/docs/_authority/note.txt"})
        if req.method == "DELETE":
            self.state["stage"] = "cancelled"
            return route.fulfill(status=204)
        if path.endswith("/accept"):
            self.state.update(stage="accepted", taxonomy_id="T1")
            return route.fulfill(status=201, json={"taxonomy_id": "T1"})
        return route.fulfill(json=self.state)

    def sent(self, method, path):
        return [b for m, p, b in self.calls if (m, p) == (method, path)]


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(10_000)
        yield page
        browser.close()


def open_run(page, state):
    api = Api(page, state)
    page.goto(f"{URL}/#/taxonomy/authority/r1")
    return api


def test_start_form_and_start(page):
    api = Api(page, run("discovering"))
    page.goto(f"{URL}/#/taxonomy/authority")
    page.get_by_label("Theme key").wait_for()
    assert page.get_by_label("Theme key").locator("option").count() == 11
    page.get_by_role("button", name="Start").click()
    page.get_by_text("Theme name is required").wait_for()
    assert not api.sent("POST", "/runs")
    page.get_by_label("Theme name").fill("Hydrogen")
    page.get_by_label("Theme key").select_option("hydrogen")
    page.get_by_label("Scope").fill("S1")
    page.get_by_label("Source guidance").fill("G1")
    page.get_by_label("Value chain").check()
    page.get_by_role("button", name="Start").click()
    page.wait_for_url("**/#/taxonomy/authority/r1")
    assert api.sent("POST", "/runs") == [{"theme_name": "Hydrogen", "theme_key": "hydrogen", "scope": "S1", "guidance": "G1", "value_chain": True}]


def test_working_message_and_cancel(page):
    open_run(page, run("discovering"))
    page.get_by_text("Hydrogen", exact=False).first.wait_for()
    page.get_by_role("button", name="Cancel").click()
    page.get_by_text("was cancelled").wait_for()


def test_run_not_found(page):
    Api(page, {}).status["GET /runs/r1"] = (404, {"detail": "run not found"})
    page.goto(f"{URL}/#/taxonomy/authority/r1")
    page.get_by_text("Run not found").wait_for()
    assert page.get_by_role("link", name="Start a new run").get_attribute("href") == "#/taxonomy/authority"


def test_source_cards_and_build_draft(page):
    api = open_run(page, run("awaiting_sources", candidates=candidates()))
    card = page.get_by_role("listitem").filter(has_text="EU Taxonomy hydrogen")
    card.get_by_text("From library").wait_for()
    assert card.get_by_role("checkbox").is_checked()
    link = card.get_by_role("link", name="EU Taxonomy hydrogen")
    assert (link.get_attribute("href"), link.get_attribute("target")) == (SRC, "_blank")
    assert card.locator('[data-covered="true"]').all_inner_texts() == ["✓ activities", "✓ thresholds"]
    assert card.locator(".chip").count() == 8
    blocked = page.get_by_role("listitem").filter(has_text="Blocked report")
    blocked.get_by_text("Not fetchable").wait_for()
    assert not blocked.get_by_role("checkbox").is_checked()
    assert page.get_by_label("Upload document", exact=True).get_attribute("accept") == ".pdf,.txt,.md"
    card.get_by_role("checkbox").uncheck()
    assert page.get_by_role("button", name="Build draft").is_disabled()
    page.get_by_label("URL", exact=True).fill("u1")
    page.get_by_role("button", name="Add URL").click()
    page.get_by_label("URL", exact=True).fill("u2")
    page.get_by_role("button", name="Add URL").click()
    page.get_by_role("button", name="Remove u2").click()
    page.get_by_label("Upload document", exact=True).set_input_files({"name": "note.txt", "mimeType": "text/plain", "buffer": b"hi"})
    page.get_by_text("note.txt").wait_for()
    page.get_by_role("button", name="Build draft").click()
    page.wait_for_function("true")
    assert api.sent("POST", "/runs/r1/sources") == [{"urls": ["u1"], "files": ["/docs/_authority/note.txt"]}]
    assert any(p == "/uploads" for _, p, _ in api.calls)


def test_error_and_restored_selection(page):
    sel = {"urls": ["https://example.org/blocked", "u9"], "files": []}
    open_run(page, run("awaiting_sources", candidates=candidates(), error="x-went-wrong", selection=sel))
    page.get_by_text("x-went-wrong").wait_for()
    assert page.get_by_role("listitem").filter(has_text="Blocked report").get_by_role("checkbox").is_checked()
    assert not page.get_by_role("listitem").filter(has_text="EU Taxonomy hydrogen").get_by_role("checkbox").is_checked()
    page.get_by_text("u9").wait_for()


def test_failed_run_and_start_again_prefills(page):
    open_run(page, run("failed", error="boom"))
    page.get_by_text("boom").wait_for()
    page.get_by_role("button", name="Start a new run").click()
    page.wait_for_url("**/#/taxonomy/authority")
    assert page.get_by_label("Theme name").input_value() == "Hydrogen"
    assert page.get_by_label("Theme key").input_value() == "hydrogen"
    assert page.get_by_label("Scope").input_value() == "S1"
    assert page.get_by_label("Source guidance").input_value() == "G1"
    assert page.get_by_label("Value chain").is_checked()


def review_state():
    return run("awaiting_review", draft=draft())


def test_review_layout(page):
    open_run(page, review_state())
    page.get_by_role("heading", name="Theme description").wait_for()
    headings = page.locator("section > h3").all_inner_texts()
    assert headings == ["Theme description", "Technologies", "Definitions", "Activities", "Thresholds", "Checklist report", "Notes"]
    assert page.get_by_role("listitem", name="Activity Electrolysis").count() == 1
    assert page.locator('li[aria-label^="Activity "]').count() == 2
    rows = page.locator("section", has=page.get_by_role("heading", name="Checklist report")).locator("tbody tr")
    assert rows.count() == 1
    assert rows.first.locator("td").all_inner_texts()[1:] == [("found" if k in ("activities", "thresholds") else "not in source") for k in CHECKLIST]
    assert page.get_by_text("Crit quote").first.get_attribute("contenteditable") is None
    assert page.get_by_role("link", name=SRC).count() > 0
    block = page.get_by_label("Activity Electrolysis")
    block.get_by_text("exiobase").wait_for()
    assert block.get_by_role("button", name="Add sector code").count() == 0
    assert page.get_by_role("button", name="Add activity").count() == 0


def test_save_keeps_citations_then_422_keeps_edit(page):
    api = open_run(page, review_state())
    page.get_by_label("Criterion 1").first.fill("New text")
    api.status["PUT /runs/r1/draft"] = (422, {"detail": "activity X has no citation"})
    page.get_by_role("button", name="Save").click()
    page.get_by_text("activity X has no citation").wait_for()
    assert page.get_by_label("Criterion 1").first.input_value() == "New text"
    del api.status["PUT /runs/r1/draft"]
    page.get_by_role("button", name="Save").click()
    page.wait_for_function("true")
    body = api.sent("PUT", "/runs/r1/draft")[-1]
    crit = body["activities"][0]["criteria"][0]
    assert (crit["text"], crit["citations"]) == ("New text", [cite("Crit quote")])


def test_role_edit_and_accept_saves_first(page):
    api = open_run(page, review_state())
    page.get_by_label("Activity Electrolysis").get_by_label("Value-chain role").select_option("upstream")
    page.get_by_role("button", name="Accept").click()
    page.get_by_text("Accepted as taxonomy T1").wait_for()
    order = [(m, p) for m, p, _ in api.calls if m in ("PUT", "POST")]
    assert order == [("PUT", "/runs/r1/draft"), ("POST", "/runs/r1/accept")]
    assert api.sent("PUT", "/runs/r1/draft")[0]["activities"][0]["value_chain_role"] == "upstream"


def test_accept_stops_when_save_fails(page):
    api = open_run(page, review_state())
    page.get_by_label("Criterion 1").first.fill("x")
    api.status["PUT /runs/r1/draft"] = (422, {"detail": "nope"})
    page.get_by_role("button", name="Accept").click()
    page.get_by_text("nope").wait_for()
    assert not api.sent("POST", "/runs/r1/accept")


def test_409_reloads_the_run(page):
    api = open_run(page, review_state())
    page.get_by_label("Criterion 1").first.fill("x")
    api.status["PUT /runs/r1/draft"] = (409, {"detail": "run is at stage accepted"})
    api.state.update(stage="accepted", taxonomy_id="T")
    page.get_by_role("button", name="Save").click()
    page.get_by_text("Accepted as taxonomy T").wait_for()


def test_no_empty_activity_save_blocked(page):
    """Removing every activity still saves: the API only rejects activities without citations."""
    api = open_run(page, review_state())
    for _ in range(2):
        page.get_by_role("button", name="Remove activity").first.click()
    page.get_by_role("button", name="Save").click()
    page.wait_for_function("true")
    assert api.sent("PUT", "/runs/r1/draft")[-1]["activities"] == []


def test_unsaved_edit_guards(page):
    open_run(page, review_state())
    page.get_by_label("Criterion 1").first.fill("edited")
    assert page.evaluate("() => { const e = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(e); return e.defaultPrevented; }")
    page.once("dialog", lambda d: d.dismiss())
    page.locator("a.nav-tab:not(.active)").first.click()  # a sidebar tab; the guard asks, and the answer is no
    assert page.get_by_label("Criterion 1").first.input_value() == "edited"
    assert page.get_by_label("Criterion 1").first.input_value() == "edited"


def test_cancel_run_then_start_again(page):
    open_run(page, review_state())
    page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Cancel").click()
    page.get_by_text("was cancelled").wait_for()
    page.get_by_role("button", name="Start a new run").click()
    assert page.get_by_label("Theme name").input_value() == "Hydrogen"


def test_library_entry_point_and_old_option_gone(page):
    page.goto(f"{URL}/#/taxonomy")
    page.get_by_role("button", name="Build from authority sources").click()
    page.wait_for_url("**/#/taxonomy/authority")
    page.goto(f"{URL}/#/taxonomy")
    page.get_by_role("button", name="New taxonomy").click()
    options = page.get_by_label("Derivation method").locator("option").all_inner_texts()
    assert options and not any("Authority source" in o for o in options)


def test_other_create_methods_and_fund_discovery_unchanged(page):
    sent = {}

    def create(route):
        sent["create"] = json.loads(route.request.post_data)
        route.fulfill(status=500, json={"detail": "stub"})

    def discover(route):
        sent["discover"] = json.loads(route.request.post_data)
        route.fulfill(json={"authority_sources": [], "thematic_funds": []})

    page.route("**/api/taxonomies", lambda r: create(r) if r.request.method == "POST" else r.fallback())
    page.route("**/api/taxonomies/discover-sources", discover)
    page.goto(f"{URL}/#/taxonomy")
    page.get_by_role("button", name="New taxonomy").click()
    page.get_by_role("button", name="Draft & save taxonomy").click()
    page.get_by_text("stub").wait_for()
    assert sent["create"] == {"name": "Electrification", "description": "", "derivation_method": "llm_draft", "use_sample_io": False,
                              "authority_urls": [], "universe_path": None, "mine_news": True}
