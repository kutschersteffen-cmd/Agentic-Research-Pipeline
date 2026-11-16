"""App-wide top bar, PR 2 (docs/superpowers/specs/2026-11-15-app-wide-top-bar-design.md) against the running app."""

import pytest

from tests.e2e.test_ui_polish_2 import URL, _open, _probe, _style, page  # noqa: F401  (page is a fixture)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

STATE_WORDS = {"has a finished run", "running", "waiting on a person", "last run failed", "no activity yet"}


def _box(loc):
    return loc.bounding_box()


def test_ac25_process_state_square(page):  # noqa: F811
    _open(page, "/#/stewardiq")
    states = page.locator(".hub-process-state")
    assert states.count() >= 1
    for s in states.all():
        marks = s.locator(".hub-mark")
        assert marks.count() == 1
        b = _box(marks.first)
        assert round(b["width"]) == 8 and round(b["height"]) == 8
        assert s.inner_text().strip() in STATE_WORDS, s.inner_text()
    assert page.locator(".hub-dot").count() == 0


def test_step_focus_visible(page):  # noqa: F811
    _open(page, "/#/stewardiq")
    step = page.locator("a.hub-step:visible").first  # the first process is folded
    step.focus()
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")
    assert _style(step, "outlineStyle") != "none"


def _runs_stub(pg, runs, pattern="**/api/runs"):
    def handle(route):
        resp = route.fetch()
        body = resp.json()
        real = body.get("runs", [])
        base = {**(real[0] if real else {"review_count": 0, "params": {}, "estimated_cost_usd": 0.0}), "company_count": 1, "completed_count": 0}
        body["runs"] = [{**base, "updated_at": "2026-11-16T00:00:00Z", "created_at": "2026-11-16T00:00:00Z", **r} for r in runs] + real
        route.fulfill(response=resp, json=body)

    pg.route(pattern, handle)


def test_ac28_running_status_is_run_blue(page):  # noqa: F811
    _runs_stub(page, [{"run_id": "e2e-run-blue", "run_type": "extraction", "status": "running"}], "**/api/runs*")
    _open(page, "/#/history")
    pill = page.locator("tr", has_text="e2e-run-blue").locator(".status-pill").first
    pill.wait_for()
    assert _style(pill, "color") == _probe(page, "--run")
    sq = pill.evaluate("e => { const s = getComputedStyle(e, '::before'); return [s.width, s.height, s.borderRadius]; }")
    assert sq == ["8px", "8px", "0px"], sq
    assert pill.inner_text().strip() == "running"


def test_status_pill_in_phone_card(page):  # noqa: F811
    _runs_stub(page, [{"run_id": "e2e-vote-pill", "run_type": "proxy_voting", "status": "completed", "company_count": 3, "completed_count": 3}], "**/api/runs*")
    _open(page, "/#/voting", 390, 844)
    row = page.locator("table.stack-on-phone tbody tr").first
    row.wait_for()
    pill, card = _box(row.locator(".status-pill").first), _box(row)
    assert pill["x"] + pill["width"] <= card["x"] + card["width"] + 0.5
    assert page.evaluate("() => document.documentElement.scrollWidth") <= 390
