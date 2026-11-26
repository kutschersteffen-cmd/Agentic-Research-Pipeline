"""Research Desk screens (spec research-desk-wave1, slice 2) against the running app, with every `/api/desk/**` request
answered by Playwright routing: start page, asking, the working steps, the checked answer, its citation panel, how it
was found, a failed turn, a missing chat, a follow-up, and the Argus routes left alone."""

import json
import os

import pytest

from arp.config import Settings

URL = os.environ.get("ARP_E2E_URL")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

NAMES = ["pick_sources", "split", "search", "rank", "write", "check"]
T0 = "2026-11-26T10:00:00Z"


def stages(**status):
    return [{"name": n, "status": status.get(n, "pending"), "ms": 100 if status.get(n) == "done" else None, "detail": None}
            for n in NAMES]


def sse(*records, end=None):
    body = "".join(f"event: stage\ndata: {json.dumps(r)}\n\n" for r in records)
    return body + (f"event: end\ndata: {json.dumps({'status': end})}\n\n" if end else "")


SENTENCES = [
    {"n": 1, "text": "Beta spent EUR 3,100 million on capex.", "status": "found", "calculation": None,
     "citations": [{"source": 1, "quote": "Group capex: EUR 3,100 million.", "grounded": True, "page": 4}]},
    {"n": 2, "text": "That is a low-carbon share of 61.3%.", "status": "calculated", "calculation": "c1",
     "citations": [{"source": 2, "quote": "Investments in renewables and grids: EUR 1,900 million.", "grounded": True, "page": None}]},
    {"n": 3, "text": "Spending rose sharply.", "status": "to_check", "calculation": None,
     "citations": [{"source": 3, "quote": "EUR 9,999 million", "grounded": False, "page": None}]},
]
CALC = {"id": "c1", "label": "Low-carbon share", "expression": "1900 / 3100 * 100", "result": 61.29, "display": "61.3", "unit": "%",
        "formula": "Low-carbon share = 1900 / 3100 * 100 = 61.3%", "error": None}


def source(n, used=True):
    return {"n": n, "kind": "report", "company_id": "acme", "company_name": "Acme Power", "filename": "acme-2025.txt",
            "doc_type": "other", "chunk_id": f"c{n}", "text": f"Passage {n} about capex.", "page": 1,
            "scores": {"bm25": 3.5 - n}, "used": used}


def turn(tid=1, status="done", check=(1, 1, 1), **kw):
    base = {"id": tid, "chat_id": 7, "question": "capex?", "mode": "quick", "status": status, "error": None, "created_at": T0,
            "finished_at": None, "stages": stages(pick_sources="done", search="done", write="done", check="done",
                                                  split="skipped", rank="skipped"),
            "sources": [source(1), source(2), source(3), source(4, used=False)],
            "answer": {"sentences": SENTENCES, "calculations": [CALC],
                       "check": dict(zip(["found", "calculated", "to_check"], check, strict=True))} if status == "done" else None}
    return {**base, **kw}


def chat(*turns):
    return {"id": 7, "title": "capex?", "created_at": T0, "scope": [{"kind": "company", "ref": "acme", "label": "Acme Power"}],
            "turns": [{"id": t["id"], "question": t["question"], "mode": t["mode"], "status": t["status"], "created_at": T0} for t in turns]}


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(10_000)
        yield page
        browser.close()


def fulfil(page, pattern, body, status=200, content_type="application/json"):
    text = body if isinstance(body, str) else json.dumps(body)
    page.route(pattern, lambda route: route.fulfill(status=status, content_type=content_type, body=text))


def open_chat(page, t, events=None):
    fulfil(page, "**/api/desk/chats/7", chat(t))
    fulfil(page, f"**/api/desk/turns/{t['id']}", t)
    if events is not None:
        fulfil(page, f"**/api/desk/turns/{t['id']}/events", events, content_type="text/event-stream")
    with page.expect_response(f"**/api/desk/turns/{t['id']}"):
        page.goto(f"{URL}/#/argus/desk/7")


def test_start_page_and_asking(page):  # AC-36, AC-37
    sent = []
    fulfil(page, "**/api/desk/chats", [{"id": 1, "title": "Capex A", "updated_at": T0, "turns": 1},
                                       {"id": 2, "title": "Capex B", "updated_at": T0, "turns": 1}])
    fulfil(page, "**/api/desk/companies*", {"total": 1, "items": [{"company_id": "acme", "name": "Acme Power", "reports": 1}]})

    def record(route):
        req = route.request
        if req.method == "GET":
            return route.fallback()
        sent.append((req.method, req.url.split("/api/")[1], req.post_data_json))
        bodies = {"POST": {"id": 7, "title": "New chat", "created_at": T0}, "PUT": {"scope": []}}
        route.fulfill(status=201 if "turns" not in req.url and req.method == "POST" else 200, content_type="application/json",
                      body=json.dumps({"turn_id": 1} if "turns" in req.url else bodies[req.method]))

    page.route("**/api/desk/chats**", record)
    with page.expect_response(lambda r: r.url.endswith("/api/desk/chats")):
        page.goto(f"{URL}/#/argus/desk")
    assert page.get_by_role("heading", name="Research Desk", exact=True).is_visible()
    recent = page.get_by_role("region", name="Recent chats")
    assert recent.get_by_text("Capex A").is_visible() and recent.get_by_text("Capex B").is_visible()
    assert page.get_by_role("button", name="Quick").get_attribute("aria-pressed") == "true"
    ask = page.get_by_role("button", name="Ask", exact=True)
    assert ask.is_disabled()

    page.get_by_placeholder("Ask anything about the companies you pick").fill("capex?")
    assert ask.is_disabled()  # no company picked yet
    with page.expect_response("**/api/desk/companies*"):
        page.get_by_role("button", name="+ Saved company").click()
    page.get_by_role("button", name="Acme Power").click()
    page.get_by_role("button", name="Thorough").click()
    page.route("**/api/desk/chats/7", lambda route: route.fulfill(content_type="application/json", body=json.dumps(chat(turn(status="running")))))
    fulfil(page, "**/api/desk/turns/1", turn(status="running"))
    fulfil(page, "**/api/desk/turns/1/events", sse(), content_type="text/event-stream")
    ask.click()
    page.wait_for_url("**/#/argus/desk/7")
    assert sent == [("POST", "desk/chats", {}), ("PUT", "desk/chats/7/scope", {"items": [{"kind": "company", "ref": "acme"}]}),
                    ("POST", "desk/chats/7/turns", {"question": "capex?", "mode": "thorough"})]


def test_working_steps_follow_the_stream(page):  # AC-38
    running = turn(status="running", mode="thorough", stages=stages())
    events = sse({"name": "pick_sources", "status": "done", "ms": 100, "detail": None},
                 {"name": "split", "status": "done", "ms": 300, "detail": None},
                 {"name": "search", "status": "running", "ms": None, "detail": None})
    open_chat(page, running, events)
    page.get_by_text("Working on it · step 3 of 6").wait_for()
    assert page.get_by_text("WORKING", exact=True).is_visible()
    assert "0.1 s" in page.locator("li", has_text="Picked the sources").inner_text()
    assert page.get_by_text("Searched the reports").is_visible()


def test_quick_steps_leave_out_skipped_ones(page):  # AC-39
    quick = turn(status="running", stages=stages(split="skipped", rank="skipped", pick_sources="running"))
    open_chat(page, quick, sse())
    page.get_by_text("Working on it · step 1 of 4").wait_for()
    assert page.get_by_text("Split the question").count() == 0 and page.get_by_text("Picked the best passages").count() == 0


def test_answer_citations_and_how_found(page):  # AC-40, AC-42, AC-43, AC-44
    open_chat(page, turn())
    assert page.get_by_role("heading", name=SENTENCES[0]["text"]).is_visible()
    assert page.get_by_text("1 to check.", exact=True).is_visible()
    for chip in ("1 in source", "1 calculated", "1 to check"):
        assert page.get_by_text(chip, exact=True).is_visible()
    assert f"{SENTENCES[1]['text']} (calculated)" in page.locator("p", has_text=SENTENCES[1]["text"]).inner_text()
    assert f"{SENTENCES[2]['text']} to check" in page.locator("p", has_text=SENTENCES[2]["text"]).inner_text()
    assert page.get_by_text("How the 61.3% was worked out").is_visible()
    assert page.get_by_text(CALC["formula"]).is_visible()

    page.get_by_role("button", name="1", exact=True).click()
    panel = page.get_by_role("dialog")
    for text in ("Acme Power", "acme-2025.txt", "Page 4", "Group capex: EUR 3,100 million.", "found word for word"):
        assert panel.get_by_text(text).first.is_visible()
    panel.get_by_role("button", name="Source 2 →").click()
    assert page.get_by_role("dialog", name="Source 2").is_visible()
    page.keyboard.press("Escape")
    assert page.get_by_role("dialog").count() == 0
    page.get_by_role("button", name="3", exact=True).click()
    assert page.get_by_role("dialog").get_by_text("not found in the source").is_visible()
    page.keyboard.press("Escape")

    page.get_by_role("link", name="How was this found?").click()
    assert page.get_by_role("heading", name="How this answer was found").is_visible()
    assert page.get_by_role("heading", name="The 3 passages the answer used").is_visible()
    ranks = page.locator("table tbody tr td:last-child").all_inner_texts()
    assert ranks == ["1st", "2nd", "3rd"]
    page.get_by_role("link", name="← Back to the answer").click()
    assert page.get_by_role("heading", name=SENTENCES[0]["text"]).is_visible()


def test_every_figure_checked(page):  # AC-41
    open_chat(page, turn(check=(2, 1, 0)))
    assert page.get_by_text("Every figure checked.").is_visible()
    assert page.get_by_text("0 to check", exact=True).is_visible()


def test_failed_turn_missing_chat_and_follow_up(page):  # AC-45, AC-46, AC-47
    failed = turn(status="failed", error="The model call failed: boom")
    open_chat(page, failed)
    assert page.get_by_text("This question failed: The model call failed: boom").is_visible()
    assert page.get_by_placeholder("Ask a follow-up or a new question").is_enabled()

    posted = []
    second = turn(tid=2, question="and in 2024?")

    def turns(route):
        posted.append(route.request.post_data_json)
        page.unroute("**/api/desk/chats/7")
        fulfil(page, "**/api/desk/chats/7", chat(failed, second))
        route.fulfill(status=202, content_type="application/json", body=json.dumps({"turn_id": 2}))

    page.route("**/api/desk/chats/7/turns", turns)
    fulfil(page, "**/api/desk/turns/2", second)
    page.get_by_placeholder("Ask a follow-up or a new question").fill("and in 2024?")
    with page.expect_response("**/api/desk/turns/2"):
        page.get_by_role("button", name="Ask", exact=True).click()
    assert posted == [{"question": "and in 2024?", "mode": "quick"}]
    assert page.get_by_role("region", name="Earlier").get_by_text("capex?").is_visible()

    fulfil(page, "**/api/desk/chats/9", {"detail": "Chat not found"}, status=404)
    with page.expect_response("**/api/desk/chats/9"):
        page.goto(f"{URL}/#/argus/desk/9")
    page.get_by_text("Chat not found.").wait_for()
