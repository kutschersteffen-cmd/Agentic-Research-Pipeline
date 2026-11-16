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
