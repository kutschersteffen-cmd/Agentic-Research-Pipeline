"""Board tab on the Agent screen (docs/superpowers/specs/2026-11-22-agent-board.md, slice 3) against the running app."""

import json
import os
import urllib.request
from pathlib import Path

import pytest

from tests.e2e.test_ui_polish_1 import URL, _open, page  # noqa: F401  (page is a fixture)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

DSN = os.environ.get("ARP_POSTGRES_DSN", "postgresql+psycopg://arp:arp@localhost:5432/arp_test")  # e2e_stack.sh's default
API = os.environ.get("ARP_E2E_API", "http://127.0.0.1:8000")
WEIGHTS = {"weights": [{"sector": "Energy", "weight": 0.125}, {"sector": "Utilities", "weight": 0.31}]}
MIND_M = "mindmap\n  root((Grow newsletter))\n    Topics\n    LinkedIn"
GROUPED_G = "flowchart LR\n  a[Find flat]:::Housing --> b[Give notice]:::Berlin\n  b --> c[Register]:::Munich\n  class b emphasis"


def _plan(status="done"):
    """Done plan D: one stored call whose result holds the sector weights."""
    from arp.orchestration.plan_store import PlanStore

    plans = PlanStore(DSN)
    pid = plans.create("Board e2e", 'u = universe_build(taxonomy_id="t", source="u.csv")\n')
    plans.set_status(pid, status)
    plans.record_call(pid, seq=1, kind="index_construct", params={}, status="done")
    plans.update_call(pid, 1, result=WEIGHTS)
    return pid


def _post(pid, kind, title, source, **extra):
    req = urllib.request.Request(f"{API}/api/agent/boards/plan/{pid}/blocks", method="POST",
                                 data=json.dumps({"kind": kind, "title": title, "source": source, **extra}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def _store_raw(pid, kind, title, source):
    """A block written straight to the tables, past the server checks (AC-48, AC-49b)."""
    from arp.agent_board.store import BoardStore

    return BoardStore(DSN).create("plan", pid, kind, title, source)


def _board(pg, pid, width=1440):
    _open(pg, f"/#/agent/{pid}", width=width)
    if width < 900:
        pg.get_by_role("button", name="Stage").click()
    return pg.locator(".board").first


def _menu(pg, title, item):
    pg.get_by_role("button", name=f"Actions for {title}").click()
    pg.get_by_role("menuitem", name=item).click()


def _titles(pg):
    return pg.locator(".board-title").all_inner_texts()


def test_board_is_the_first_tab_and_starts_empty(page):  # noqa: F811  AC-54
    board = _board(page, _plan())
    assert page.get_by_role("tab").all_inner_texts()[:4] == ["Board", "Script", "Diff", "Audit"]
    assert page.get_by_role("tab", name="Board").get_attribute("aria-selected") == "true"
    assert board.get_by_text("Nothing on the board yet. Ask for a chart, diagram, table or checklist.").is_visible()
    assert board.get_by_role("textbox").get_attribute("placeholder") == "Ask the agent to draw something…"


def test_move_up_persists_and_undo_restores_an_edit(page):  # noqa: F811  AC-23, AC-25b
    pid = _plan()
    _post(pid, "note", "One", "1")
    _post(pid, "note", "Why", "a")
    _board(page, pid)
    _menu(page, "Why", "Move up")
    page.wait_for_function("document.querySelector('.board-title')?.textContent === 'Why'")
    page.reload()
    page.wait_for_load_state("networkidle")
    assert _titles(page) == ["Why", "One"]
    page.get_by_role("button", name="Actions for One").click()
    assert page.get_by_role("menuitem", name="Undo last change").count() == 0
    page.keyboard.press("Escape")
    _menu(page, "Why", "Edit")
    page.get_by_label("Source of Why").fill("b")
    page.get_by_role("button", name="Save").click()
    block = page.locator(".board-block", has=page.get_by_role("heading", name="Why"))
    block.locator(".board-note", has_text="b").wait_for()
    _menu(page, "Why", "Undo last change")
    block.locator(".board-note", has_text="a").wait_for()


def test_note_shows_html_as_text_and_no_script_link(page):  # noqa: F811  AC-24
    pid = _plan()
    _post(pid, "note", "N", "<img src=x onerror=\"document.title='hit'\">\n\n[a](javascript:alert(1))")
    _board(page, pid)
    note = page.locator(".board-note")
    assert "<img src=x" in note.inner_text()
    assert note.locator("a").count() == 0 and note.locator("img").count() == 0
    assert page.title() != "hit"


def test_delete_then_undo_puts_the_agent_table_back(page):  # noqa: F811  AC-25d, AC-25e, AC-18
    pid = _plan()
    _post(pid, "note", "First", "x")
    _post(pid, "table", "T", {"columns": ["sector", "weight"], "rows": [["Energy", 0.125], ["Total", 0.435]]},
          origin="agent", unverified=[0.435])
    _post(pid, "note", "Last", "y")
    _board(page, pid)
    assert page.get_by_text("Not in ARP data: 0.435").is_visible()
    _menu(page, "T", "Delete")
    page.get_by_text("Block deleted").wait_for()
    assert _titles(page) == ["First", "Last"]
    page.get_by_role("button", name="Undo").click()
    page.wait_for_function("document.querySelectorAll('.board-title').length === 3")
    assert _titles(page) == ["First", "T", "Last"]
    block = page.locator(".board-block", has=page.get_by_role("heading", name="T"))
    assert block.locator(".board-label").inner_text() == "Agent"
    assert block.get_by_text("Not in ARP data: 0.435").is_visible()


def test_downloads_and_table_csv_edit(page):  # noqa: F811  AC-25c, AC-25f, AC-25h, AC-63
    pid = _plan()
    _post(pid, "table", "T", {"columns": ["a", "b"], "rows": [[1, 2]]})
    _post(pid, "chart", "Sector weights 2026", {"mark": "bar", "data": {"values": [{"s": "Energy", "w": 0.125}]},
                                                "encoding": {"x": {"field": "s", "type": "nominal"}, "y": {"field": "w", "type": "quantitative"}}})
    _post(pid, "checklist", "C", {"items": [{"text": "a", "done": True}, {"text": "b", "done": False}]})
    _board(page, pid)
    assert page.locator("img.board-chart").get_attribute("src").startswith("data:image/svg+xml")
    for title, name, start in [("T", "T.csv", "a,b"), ("Sector weights 2026", "Sector_weights_2026.svg", "<svg"), ("C", "C.md", "- [x] a\n- [ ] b")]:
        with page.expect_download() as d:
            _menu(page, title, "Download")
        assert d.value.suggested_filename == name
        assert Path(d.value.path()).read_text(encoding="utf-8").startswith(start)
    _menu(page, "T", "Edit")
    page.get_by_label("Source of T").fill("a,b\n1,\nx,2.5")
    with page.expect_response(lambda r: r.request.method == "PATCH") as res:
        page.get_by_role("button", name="Save").click()
    assert res.value.json()["source"] == {"columns": ["a", "b"], "rows": [[1, None], ["x", 2.5]]}


def test_a_refused_edit_keeps_the_field_open_with_the_detail(page):  # noqa: F811  AC-25 Edit
    pid = _plan()
    _post(pid, "table", "T", {"columns": ["a", "b"], "rows": [[1, 2]]})
    _board(page, pid)
    _menu(page, "T", "Edit")
    page.get_by_label("Source of T").fill("a,b\n1")
    page.get_by_role("button", name="Save").click()
    page.get_by_text("row 1 has 1 cells, expected 2").wait_for()
    assert page.get_by_label("Source of T").is_visible()


def test_tiles_checklist_and_live_labels(page):  # noqa: F811  AC-50, AC-51, AC-52, AC-53
    pid = _plan()
    _post(pid, "tiles", "Key", {"tiles": [{"label": "Utilities", "value": 0.31, "format": "percent", "change": 0.04, "note": "vs Q2"},
                                          {"label": "Issuers", "value": 1234.5, "change": -12}]})
    _post(pid, "checklist", "C", {"items": [{"text": "Call vendor", "done": False}]})
    _post(pid, "table", "W", {"live": "/steps/0/result/weights", "columns": ["sector", "weight"]})
    _post(pid, "table", "Gone", {"live": "/steps/5/result", "columns": ["a"]})
    _board(page, pid)
    assert page.locator(".board-tile").all_inner_texts() == ["Utilities\n31.0%\n+4.0 pts\nvs Q2", "Issuers\n1,234.5\n-12"]
    w = page.locator(".board-block", has=page.get_by_role("heading", name="W", exact=True))
    assert w.locator(".board-label").inner_text() == "Live · step 1"
    assert "0.31" in w.locator("table").inner_text()
    assert page.get_by_text("live data not found: /steps/5/result").is_visible()
    with page.expect_response(lambda r: r.request.method == "PATCH"):
        page.get_by_label("Call vendor").check()
    page.reload()
    page.wait_for_load_state("networkidle")
    assert page.get_by_label("Call vendor").is_checked()
    _menu(page, "C", "Undo last change")
    page.wait_for_function("!document.querySelector('.board-checklist input').checked")


def test_diagrams_draw_in_a_sealed_frame(page):  # noqa: F811  AC-47, AC-49, AC-49b, AC-49d, AC-48
    pid = _plan()
    _post(pid, "diagram", "M", MIND_M)
    _post(pid, "diagram", "G", GROUPED_G)
    _store_raw(pid, "diagram", "L", 'flowchart LR\n  a --> b\n  click a href "https://example.com"')
    _store_raw(pid, "diagram", "Bad", "flowchart LR\n  a -->")
    hosts = []
    page.on("request", lambda r: hosts.append(r.url.split("/")[2]))
    _board(page, pid)
    page.get_by_text("This diagram could not be drawn:").wait_for()
    assert "flowchart LR\n  a -->" in page.locator(".board-source").inner_text()
    assert page.locator("iframe.board-frame-failed").bounding_box()["height"] == 0  # no blank gap above the message
    frames = page.locator("iframe.board-frame:not(.board-frame-failed)")
    assert frames.count() == 3
    for i in range(3):
        assert frames.nth(i).get_attribute("sandbox") == "allow-scripts"
    by_path = [f for f in page.frames if f.url.endswith("board-diagram.html")]
    assert len(by_path) == 4
    drawn = {}
    for f in by_path:
        f.wait_for_function("document.querySelector('#diagram svg') || true")
        text = f.locator("#diagram").inner_text() if f.locator("#diagram svg").count() else ""
        drawn[text] = f
    m = next(f for t, f in drawn.items() if "Grow newsletter" in t)
    assert all(x in m.evaluate("document.querySelector('#diagram svg').textContent") for x in ("Topics", "LinkedIn"))
    g = next(f for t, f in drawn.items() if "Give notice" in t)
    fills = g.evaluate("""() => ['Find flat', 'Give notice', 'Register'].map((t) => {
        const node = [...document.querySelectorAll('g.node')].find((n) => n.textContent.includes(t));
        return getComputedStyle(node.querySelector('rect, path, polygon')).fill; })""")
    assert len(set(fills)) == 3
    width = g.evaluate("""() => {
        const node = [...document.querySelectorAll('g.node')].find((n) => n.textContent.includes('Give notice'));
        return getComputedStyle(node.querySelector('rect, path, polygon')).strokeWidth; }""")
    assert width == "3px"
    legend = page.locator(".board-legend").inner_text()
    assert all(x in legend for x in ("Housing", "Berlin", "Munich", "Bold outline: key step"))
    link = next(f for t, f in drawn.items() if t.strip() and "Give notice" not in t and "Grow newsletter" not in t)
    assert link.evaluate("document.querySelectorAll('svg a').length") == 0
    assert link.evaluate("[...document.querySelectorAll('svg *')].filter((e) => e.hasAttribute('href') || e.hasAttribute('xlink:href')).length") == 0
    # The clickable box keeps the place and label Mermaid gave it on the <a> wrapper: inside the drawing, left of `b`.
    boxes = link.evaluate("""() => {
        const svg = document.querySelector('#diagram svg').getBoundingClientRect();
        return ['a', 'b'].map((t) => {
            const n = [...document.querySelectorAll('g.node')].find((g) => g.textContent.trim() === t).getBoundingClientRect();
            return { left: n.left - svg.left, top: n.top - svg.top, width: n.width, right: svg.right - n.right }; }); }""")
    a_box, b_box = boxes
    assert a_box["left"] > 0 and a_box["top"] > 0 and a_box["width"] > 20, a_box
    assert a_box["left"] + a_box["width"] < b_box["left"], boxes
    # Text is never shrunk below 11 px to fit the narrow stage; a wide diagram scrolls inside its card instead.
    for f in by_path:
        size = f.evaluate("(() => { const s = document.querySelector('#diagram svg'); return s && 14 * s.getBoundingClientRect().width / s.viewBox.baseVal.width; })()")
        assert size is None or size >= 10.99, size
    assert page.evaluate("document.documentElement.scrollWidth") <= 1440
    allowed = {URL.split("/")[2], API.split("/")[2], "localhost:8000", "fonts.googleapis.com", "fonts.gstatic.com"}
    assert set(hosts) <= allowed, set(hosts) - allowed


def test_phone_board_fills_the_drawer_without_page_scroll(page):  # noqa: F811  AC-26
    pid = _plan()
    cols = [f"c{i}" for i in range(20)]
    _post(pid, "table", "Wide", {"columns": cols, "rows": [[f"value {i}" for i in range(20)]]})
    board = _board(page, pid, width=390)
    board.locator("table").wait_for()
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    box = board.locator(".board-table-box")
    assert box.evaluate("e => e.scrollWidth > e.clientWidth")


def test_draw_shows_a_placeholder_then_the_agent_block(page):  # noqa: F811  AC-25
    pid = _plan()

    def draw(route):
        page.wait_for_timeout(600)  # long enough to see `Drawing…`
        made = _post(pid, "note", "Weights", "drawn", origin="agent")
        route.fulfill(json=made)

    page.route("**/draw", draw)
    _board(page, pid)
    field = page.get_by_placeholder("Ask the agent to draw something…")
    field.fill("chart the weights")
    field.press("Enter")
    page.locator(".board-drawing", has_text="Drawing…").wait_for()
    assert field.is_disabled()
    block = page.locator(".board-block", has=page.get_by_role("heading", name="Weights"))
    block.wait_for()
    assert block.locator(".board-label").inner_text() == "Agent"
    assert page.locator(".board-drawing").count() == 0


def test_a_diagram_that_names_an_outside_image_loads_nothing(page):  # noqa: F811  AC-49c
    pid = _plan()
    _store_raw(pid, "diagram", "S", 'sequenceDiagram\n  participant A as Analyst\n  properties A: {"icon": "https://example.com/i.png"}\n  A->>A: Review')
    responses = []
    page.on("response", lambda r: responses.append(r.url))
    _board(page, pid)
    frame = None
    for _ in range(50):
        frame = next((f for f in page.frames if f.url.endswith("board-diagram.html") and f.locator("#diagram svg").count()), None)
        if frame:
            break
        page.wait_for_timeout(100)
    assert frame and "Analyst" in frame.evaluate("document.querySelector('#diagram svg').textContent")
    page.wait_for_timeout(500)
    assert not [u for u in responses if "example.com" in u]


def test_a_running_plan_redraws_live_blocks_without_a_reload(page):  # noqa: F811  AC-57, AC-64
    from arp.orchestration.plan_store import PlanStore

    # The plan stays `done` in the tables, so the API's runner leaves it alone; the browser is told it runs.
    pid = _plan()
    shown = {"status": "running"}

    def plan(route):
        resp = route.fetch()
        route.fulfill(response=resp, json={**resp.json(), "status": shown["status"]})

    page.route(f"**/api/plans/{pid}", plan)
    _post(pid, "table", "W", {"live": "/steps/0/result/weights", "columns": ["sector", "weight"]})
    _board(page, pid)
    assert "0.31" in page.locator(".board-table").inner_text()
    plans = PlanStore(DSN)
    plans.update_call(pid, 1, result={"weights": [{"sector": "Energy", "weight": 0.125}, {"sector": "Utilities", "weight": 0.4}]})
    page.wait_for_function("document.querySelector('.board-table').textContent.includes('0.4')", timeout=15_000)
    plans.update_call(pid, 1, result={"weights": [{"sector": "Energy", "weight": 0.125}, {"sector": "Utilities", "weight": 0.5}]})
    shown["status"] = "done"
    page.wait_for_function("document.querySelector('.board-table').textContent.includes('0.5')", timeout=15_000)
