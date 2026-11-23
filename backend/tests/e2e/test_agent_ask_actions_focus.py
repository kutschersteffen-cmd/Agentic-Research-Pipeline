"""Focus after `Explore` and `Draft a plan` under an answer (spec agent-panel-code-mode, slice 14, UI review of #664).

The buttons are disabled while their request runs, so focus would drop to <body>. The ask thread and the two POSTs
are answered by page.route, so no model or sandbox stand-in is needed.
"""

import json
import os
import time

import pytest

from arp.config import Settings

URL = os.environ.get("ARP_E2E_URL")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

T = "11111111-1111-4111-8111-111111111111"
CREATED = "2026-11-22T10:00:00+00:00"
ASK = {"id": T, "thread_id": T, "question": "Sector weights?", "standalone_question": "Sector weights of MSCI World?",
       "tool": "benchmark_sectors", "response": None, "error": None, "asked_by": "dev", "created_at": CREATED,
       "plans": [], "explorations": []}
EXPLORATION = {"id": "22222222-2222-4222-8222-222222222222", "question": "Sector weights of MSCI World?",
               "code": "return 1", "status": "done", "result": 1, "error": None, "tool_calls": [], "model": "stand-in",
               "cost_usd": 0.0, "created_at": CREATED, "accepted_by": None, "accepted_at": None,
               "label": "exploratory", "source_ask_id": T,
               "source_ask": {"question": "Sector weights?", "thread_id": T}}


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        yield page
        browser.close()


def _thread(page, explore_status=200):
    def json_reply(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

    page.route("**/api/agent/ask-threads", lambda r: json_reply(r, [
        {"thread_id": T, "title": "Sector weights?", "status": "answered", "created_at": CREATED, "asks": 1}]))
    page.route(lambda url: "/api/agent/asks?" in url, lambda r: json_reply(r, [ASK]))
    def explore(route):
        if route.request.method != "POST":
            return route.continue_()
        time.sleep(1)  # a real exploration takes a while; the button sits disabled meanwhile
        json_reply(route, EXPLORATION if explore_status == 200 else {"detail": "ask not found"}, explore_status)

    page.route("**/api/agent/explorations", explore)
    page.goto(f"{URL}/#/agent/ask/{T}")
    return page.locator(".ask-turn").first


def _focused(page):
    return page.evaluate("() => [document.activeElement.tagName, document.activeElement.textContent.trim()]")


def test_explore_moves_focus_to_the_new_link_card(page):
    turn = _thread(page)
    turn.get_by_role("button", name="Explore").focus()
    page.keyboard.press("Enter")
    turn.get_by_role("link", name="Exploration: Sector weights of MSCI World?").wait_for()
    page.wait_for_function("() => document.activeElement.tagName === 'A'", timeout=5_000)
    assert _focused(page) == ["A", "Exploration: Sector weights of MSCI World?"]


def test_a_failed_explore_returns_focus_to_its_button(page):
    turn = _thread(page, explore_status=404)
    turn.get_by_role("button", name="Explore").focus()
    page.keyboard.press("Enter")
    turn.get_by_role("alert").wait_for()
    page.wait_for_function("() => document.activeElement.tagName === 'BUTTON'", timeout=5_000)
    assert _focused(page) == ["BUTTON", "Explore"]
