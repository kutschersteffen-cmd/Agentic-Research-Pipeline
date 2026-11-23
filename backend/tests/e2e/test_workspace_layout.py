"""Workspace overview layout (expressive-ui-orb slice 3, review of #674) against the running app."""

import pytest

from tests.e2e.test_ui_polish_2 import URL, _open, page  # noqa: F401  (page is a fixture)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

WORKSPACES = ["stewardiq", "transitionIntel", "rdLab", "dataHub"]
T = "2026-11-22T10:00:00Z"
R1 = {"run_id": "r1", "run_type": "emerging_themes", "status": "running", "review_count": 0, "company_count": 480,
      "completed_count": 212, "failed_count": 0, "params": {}, "created_at": T, "updated_at": T}

# Each word of the title, as the lines it was laid out on: a word split over two lines shows up as two entries.
WORD_LINES = """e => { const r = document.createRange(); const t = e.firstChild; const out = [];
  for (const m of t.data.matchAll(/\\S+/g)) { r.setStart(t, m.index); r.setEnd(t, m.index + m[0].length);
    out.push([m[0], new Set([...r.getClientRects()].map((x) => Math.round(x.top))).size]); }
  return out; }"""


@pytest.mark.parametrize("width", [390, 761, 900, 1081, 1100, 1170, 1280, 1421, 1440, 1600])
def test_title_wraps_between_words(page, width):  # noqa: F811
    for ws in WORKSPACES:
        _open(page, f"/#/{ws}", width, 900)
        h1 = page.locator(".page > h1")
        split = [w for w, lines in h1.evaluate(WORD_LINES) if lines > 1]
        assert split == [], (ws, width, split)


@pytest.mark.parametrize("width", [1100, 1280, 1440])
def test_step_text_stays_in_its_card(page, width):  # noqa: F811
    page.route("**/api/runs*", lambda route: route.fulfill(json={"runs": [R1]}))
    _open(page, "/#/rdLab", width, 900)
    sec = page.locator("section.hub-process", has=page.get_by_role("heading", name="Build a thematic portfolio"))
    sec.locator("button.hub-step").first.wait_for()
    over = sec.evaluate("""s => [...s.querySelectorAll('button.hub-step')].flatMap((b) => {
        const box = b.getBoundingClientRect();
        return [...b.querySelectorAll('span')].filter((x) => x.getBoundingClientRect().right > box.right + 0.5).map((x) => x.textContent); })""")
    assert over == [], (width, over)


def test_no_empty_ask_column_for_a_viewer(page):  # noqa: F811
    def me(route):
        resp = route.fetch()
        route.fulfill(response=resp, json={**resp.json(), "role": "viewer"})

    page.route("**/api/me", me)
    _open(page, "/#/rdLab")
    assert page.get_by_role("complementary", name="Ask ARP").count() == 0
    page_box = page.locator(".page.hub-ws").bounding_box()
    fig = page.locator(".hub-ws-fig").bounding_box()
    panel = page.locator("section.hub-process").first.bounding_box()
    assert abs((fig["x"] + fig["width"]) - (page_box["x"] + page_box["width"])) <= 1, (fig, page_box)
    assert panel["width"] >= page_box["width"] - 1, (panel, page_box)
