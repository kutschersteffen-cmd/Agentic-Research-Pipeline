"""Focus around "Turn into a plan…" (spec agent-panel-code-mode, slice 12; UI review on PR #665), against the running
app with the exploration and plan routes answered by the test."""

import pytest

from tests.e2e.test_ui_polish_1 import URL, _open, page  # noqa: F401  (page is a fixture)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

E = "11111111-1111-4111-8111-111111111111"
EXPLORATION = {
    "id": E, "question": "Which issuers lack a 2025 report?", "code": "return 1", "status": "done",
    "result": [{"issuer": f"Issuer {i}", "report_2025": False} for i in range(30)], "error": None, "tool_calls": [],
    "model": "stand-in", "cost_usd": 0.0, "created_at": "2026-11-22T10:00:00Z", "accepted_by": "alice",
    "accepted_at": "2026-11-22T10:01:00Z", "label": "accepted",
}
SCRIPT = "\n".join(f'u{i} = universe_build(taxonomy_id="t", source="s{i}.csv")' for i in range(30)) + "\n"
PLAN = {
    "id": "plan_e2e_turn", "brief": "Fetch the missing reports", "script": SCRIPT,
    "dry_run": [{"seq": i + 1, "kind": "universe_build", "params": {"source": f"s{i}.csv", "taxonomy_id": "t"}, "depends_on": None}
                for i in range(30)],
    "status": "draft", "approved_by": None, "approved_at": None, "error": None, "version": 1, "previous_scripts": [],
    "created_at": "2026-11-22T10:02:00Z", "source_ask_id": None, "source_ask": None, "source_exploration_id": E,
    "source_exploration": {"question": EXPLORATION["question"]}, "budget_usd": None, "planner_cost_usd": 0.0,
    "calls": [], "spent_usd": 0.0,
}


def _focused_id(pg) -> str:
    return pg.evaluate("document.activeElement && (document.activeElement.id || document.activeElement.tagName)")


def _routes(pg, plan_reply):
    pg.route(f"**/api/agent/explorations/{E}", lambda r: r.fulfill(json=EXPLORATION))
    pg.route(f"**/api/agent/explorations/{E}/plan", plan_reply)
    pg.route(f"**/api/plans/{PLAN['id']}", lambda r: r.fulfill(json=PLAN))


def _open_field(pg):
    _open(pg, f"/#/agent/exploration/{E}")
    pg.get_by_role("button", name="Turn into a plan…").click()


def test_cancel_returns_focus_to_turn_into_a_plan(page):  # noqa: F811
    _routes(page, lambda r: r.fulfill(json=PLAN))
    _open_field(page)
    page.get_by_role("button", name="Cancel").click()
    focused = page.evaluate("document.activeElement.textContent")
    assert focused == "Turn into a plan…"


def test_refused_draft_focuses_the_error(page):  # noqa: F811
    _routes(page, lambda r: r.fulfill(status=422, json={"detail": "line 1: bad"}))
    _open_field(page)
    page.get_by_role("button", name="Draft plan").click()
    page.get_by_text("line 1: bad").wait_for()
    assert _focused_id(page) == "agent-exploration-plan-error"


def test_drafted_plan_opens_at_its_brief_with_focus(page):  # noqa: F811
    _routes(page, lambda r: r.fulfill(json=PLAN))
    _open_field(page)
    page.get_by_role("button", name="Draft plan").click()
    page.wait_for_url(f"**/#/agent/{PLAN['id']}")
    heading = page.locator("#agent-brief-h")
    heading.wait_for()
    page.wait_for_timeout(500)  # let the stream settle: it must not follow the long plan down
    assert _focused_id(page) == "agent-brief-h"
    box, scroller = heading.bounding_box(), page.locator(".agent-scroll").bounding_box()
    assert box["y"] >= scroller["y"] - 1 and box["y"] + box["height"] <= scroller["y"] + scroller["height"]
