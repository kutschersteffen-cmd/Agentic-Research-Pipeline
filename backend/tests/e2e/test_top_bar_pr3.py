"""App-wide top bar, PR 3: interactive process flows (docs/superpowers/specs/2026-11-15-app-wide-top-bar-design.md,
AC-33..AC-42) against the running app."""

import re
from pathlib import Path

import pytest

from tests.e2e.test_top_bar_pr2 import _runs_stub
from tests.e2e.test_ui_polish_2 import URL, _open, _probe, _style, page  # noqa: F401  (page is a fixture)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

STATE_LABEL = {"done": "has a finished run", "now": "running", "wait": "waiting on a person", "failed": "last run failed", "idle": "no activity yet"}
DETAILS = re.compile(r" details$")


def _first_open_process(pg):
    """P: the first process whose steps show without opening a fold."""
    for sec in pg.locator("section.hub-process").all():
        if sec.locator("ol.hub-flow").count() and sec.locator("details ol.hub-flow").count() == 0:
            return sec
    raise AssertionError("no unfolded process on the page")


def _steps(sec):
    return sec.locator("button.hub-step")


def _label(btn):
    return btn.locator(".hub-step-title").evaluate("e => e.firstChild.textContent.trim()")


def _state(btn):
    return re.search(r"hub-step-(done|now|wait|failed|idle)\b", btn.get_attribute("class")).group(1)


def _route_of(label):
    """The step's route as `stepHref` builds it, read from the step's own line in lib/processes.ts."""
    src = (Path(__file__).resolve().parents[3] / "frontend/src/lib/processes.ts").read_text()
    line = next(ln for ln in src.splitlines() if f'label: "{label}"' in ln)
    tab = re.search(r'tab: "([^"]+)"', line).group(1)
    sub = re.search(r'sub: "([^"]+)"', line)
    return f"#/{tab}/{sub.group(1)}" if sub else f"#/{tab}"


def _panel(sec):
    return sec.locator("ol.hub-flow + [role=region]")


def _route(btn, sec):
    """The step's route, read from the panel's Open link once that step is open."""
    return _panel(sec).get_by_role("link", name=re.compile(r"^Open ")).get_attribute("href")


def test_ac33_steps_are_buttons(page):  # noqa: F811
    _open(page, "/#/stewardiq")
    p = _first_open_process(page)
    cards = p.locator(".hub-step:not(.hub-step-planned)")
    assert cards.count() >= 3
    for c in cards.all():
        assert c.evaluate("e => e.tagName") == "BUTTON"
        assert c.get_attribute("aria-expanded") == "false"
    assert page.get_by_role("region", name=DETAILS).count() == 0


def test_ac34_panel_contents(page):  # noqa: F811
    _open(page, "/#/stewardiq")
    p = _first_open_process(page)
    n = p.locator(".hub-step").count()
    btn = _steps(p).nth(1)
    label, state, does = _label(btn), _state(btn), btn.locator(".hub-step-about").inner_text().strip()
    btn.click()
    assert btn.get_attribute("aria-expanded") == "true"
    panel = _panel(p)
    assert panel.count() == 1
    assert panel.get_attribute("aria-label") == f"{label} details"
    text = panel.inner_text()
    assert f"Step 2 of {n}" in text
    assert does in text
    assert STATE_LABEL[state] in text
    link = panel.get_by_role("link", name=f"Open {label} →")
    assert link.count() == 1
    assert link.get_attribute("href") == _route_of(label)


def test_ac35_moves_panel(page):  # noqa: F811
    _open(page, "/#/stewardiq")
    p = _first_open_process(page)
    _steps(p).nth(1).click()
    _steps(p).nth(2).click()
    expanded = [b.get_attribute("aria-expanded") for b in _steps(p).all()]
    assert expanded.count("true") == 1 and expanded[2] == "true", expanded
    assert p.get_by_role("region", name=DETAILS).count() == 1
    assert _panel(p).get_attribute("aria-label") == f"{_label(_steps(p).nth(2))} details"


def test_ac35b_closes(page):  # noqa: F811
    _open(page, "/#/stewardiq")
    p = _first_open_process(page)
    btn = _steps(p).nth(1)
    btn.click()
    btn.click()
    assert p.get_by_role("region", name=DETAILS).count() == 0
    assert btn.get_attribute("aria-expanded") == "false"


def test_ac36_open_navigates(page):  # noqa: F811
    _open(page, "/#/stewardiq")
    p = _first_open_process(page)
    n = p.locator(".hub-step").count()
    btn = _steps(p).nth(1)
    btn.click()
    route = _route(btn, p)
    _panel(p).get_by_role("link", name=re.compile(r"^Open ")).click()
    page.wait_for_function("r => location.hash === r", arg=route)
    bar = page.get_by_role("navigation", name="Process progress")
    bar.wait_for()
    assert f"Step 2 of {n}" in bar.inner_text()


def test_ac37_esc(page):  # noqa: F811
    _open(page, "/#/stewardiq")
    p = _first_open_process(page)
    btn = _steps(p).nth(1)
    btn.click()
    _panel(p).get_by_role("link", name=re.compile(r"^Open ")).focus()
    page.keyboard.press("Escape")
    assert p.get_by_role("region", name=DETAILS).count() == 0
    assert btn.evaluate("e => e === document.activeElement")


def test_ac39b_reached(page):  # noqa: F811
    _open(page, "/#/stewardiq")
    for flow in page.locator("ol.hub-flow:visible").all():
        items = flow.locator(":scope > li").all()
        done = [i for i, li in enumerate(items) if li.locator(".hub-step-done").count()]
        expect = set(range(done[-1] + 1)) if done else set()
        reached = {i for i, li in enumerate(items) if "reached" in li.get_attribute("class").split()}
        assert reached == expect, (reached, expect)


def test_ac40_survives_poll(page):  # noqa: F811
    _open(page, "/#/stewardiq")
    p = _first_open_process(page)
    btn = _steps(p).nth(1)
    btn.click()
    page.wait_for_timeout(20_000)
    assert _panel(p).count() == 1
    assert btn.get_attribute("aria-expanded") == "true"


def test_ac41_phone(page):  # noqa: F811
    _open(page, "/#/stewardiq", 390, 844)
    p = _first_open_process(page)
    _steps(p).nth(1).click()
    # process-flow-viewer D2/AC-3 (owner, 23 Nov 2026) supersedes "one left edge": on a phone the steps are one
    # scrolling row, so they share one top edge.
    tops = [b.bounding_box()["y"] for b in p.locator(".hub-step").all()]
    assert max(tops) - min(tops) <= 1, tops
    link = _panel(p).get_by_role("link", name=re.compile(r"^Open "))
    assert link.bounding_box()["height"] >= 44
    assert page.evaluate("document.documentElement.scrollWidth") <= 390


def test_ac42_lede(page):  # noqa: F811
    _open(page, "/#/stewardiq")
    lede = page.locator(".page > h1 + p").inner_text()
    # ui-trim-workspaces C9: the intro is only the purpose; the legend line sits under the flows.
    assert "Click a step for its details; open it from there." not in lede
    assert "Open a step to work in its screen" not in lede
    assert page.get_by_text("typed in by hand, not passed on.").count() == 1


def _proxy(pg):
    return pg.locator("section.hub-process", has=pg.get_by_role("heading", name="Proxy season"))


def test_running_step_blue(page):  # noqa: F811
    _runs_stub(page, [{"run_id": "e2e-pr3-run", "run_type": "proxy_voting", "status": "running", "review_count": 0}], "**/api/runs*")
    _open(page, "/#/stewardiq")
    btn = _steps(_proxy(page)).first
    assert _state(btn) == "now"
    assert _style(btn, "borderTopColor") == _probe(page, "--run")
    assert _style(btn, "boxShadow") != "none"
    assert "run-into" in btn.locator("xpath=..").get_attribute("class").split()
    anim = btn.locator(".hub-step-status").evaluate("e => getComputedStyle(e, '::before').animationName")
    assert anim == "hub-pulse"


def test_pulse_off_under_reduced_motion(page):  # noqa: F811
    _runs_stub(page, [{"run_id": "e2e-pr3-still", "run_type": "proxy_voting", "status": "running", "review_count": 0}], "**/api/runs*")
    page.emulate_media(reduced_motion="reduce")
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(URL + "/#/stewardiq")
    page.wait_for_load_state("networkidle")
    btn = _steps(_proxy(page)).first
    assert _state(btn) == "now"  # else every square reads "none" and this proves nothing
    assert btn.locator(".hub-step-status").evaluate("e => getComputedStyle(e, '::before').animationName") == "none"


# Review Focus (plan): inputs the AC rows do not exercise.


def test_panel_inside_fold(page):  # noqa: F811
    _open(page, "/#/stewardiq")
    fold = page.locator("details.hub-process-fold").first
    fold.locator("summary").click()
    fold.locator("button.hub-step").first.click()
    assert fold.locator("ol.hub-flow + [role=region]").count() == 1
    page.wait_for_timeout(16_000)  # one idle poll
    assert fold.evaluate("e => e.open")
    assert fold.locator("ol.hub-flow + [role=region]").count() == 1


def test_panel_follows_state(page):  # noqa: F811
    flip = {"done": False}  # the test flips the run, not the clock, so a slow first load cannot skip "running"

    def handle(route):
        resp = route.fetch()
        body = resp.json()
        real = body.get("runs", [])
        base = {**(real[0] if real else {"review_count": 0, "params": {}, "estimated_cost_usd": 0.0}), "company_count": 1, "completed_count": 0}
        status = "completed" if flip["done"] else "running"
        body["runs"] = [{**base, "review_count": 0, "run_id": "e2e-pr3-flip", "run_type": "proxy_voting", "status": status, "updated_at": "2026-11-16T00:00:00Z", "created_at": "2026-11-16T00:00:00Z"}] + real
        route.fulfill(response=resp, json=body)

    page.route("**/api/runs*", handle)
    _open(page, "/#/stewardiq")
    sec = _proxy(page)
    btn = _steps(sec).first
    btn.click()
    panel = _panel(sec)
    assert STATE_LABEL["now"] in panel.inner_text()
    flip["done"] = True
    page.wait_for_function("() => document.querySelector('#step-panel-proxy')?.innerText.includes('has a finished run')", timeout=20_000)
    assert btn.get_attribute("aria-expanded") == "true"
    assert "e2e-pr3-flip" in panel.inner_text()


def test_keyboard_toggle_and_esc(page):  # noqa: F811
    _open(page, "/#/stewardiq")
    p = _first_open_process(page)
    btn = _steps(p).nth(1)
    btn.focus()
    page.keyboard.press("Enter")
    assert btn.get_attribute("aria-expanded") == "true"
    page.keyboard.press("Space")
    assert btn.get_attribute("aria-expanded") == "false"
    page.keyboard.press("Space")
    page.keyboard.press("Escape")
    assert _panel(p).count() == 0
    assert btn.evaluate("e => e === document.activeElement")


def test_step_button_looks_like_card(page):  # noqa: F811
    _open(page, "/#/stewardiq")
    btn = _steps(_first_open_process(page)).first
    btn.hover()
    assert _style(btn, "backgroundColor") == _probe(page, "--panel", "backgroundColor")
    assert _style(btn, "textAlign") == "left"
    assert _style(btn, "marginTop") == "0px"


def test_panels_per_process(page):  # noqa: F811
    _open(page, "/#/stewardiq")
    secs = [s for s in page.locator("section.hub-process").all() if s.locator("details ol.hub-flow").count() == 0]
    if len(secs) < 2:
        fold = page.locator("details.hub-process-fold").first
        fold.locator("summary").click()
        secs = [s for s in page.locator("section.hub-process").all() if s.locator("button.hub-step:visible").count()]
    a, b = secs[0], secs[1]
    _steps(a).first.click()
    _steps(b).first.click()
    assert page.get_by_role("region", name=DETAILS).count() == 2
    ids = page.locator("[role=region][id^=step-panel-]").evaluate_all("els => els.map(e => e.id)")
    assert len(set(ids)) == 2, ids


# Final review fixes.


def test_step_card_keeps_body_tracking(page):  # noqa: F811
    _open(page, "/#/stewardiq")
    btn = _steps(_first_open_process(page)).first
    assert _style(btn, "letterSpacing") == page.evaluate("getComputedStyle(document.body).letterSpacing")


def test_panel_opened_before_first_poll_stays_open(page):  # noqa: F811
    """A panel opened while runs are still loading stays open (and keeps focus) when the process turns out idle."""
    held = []
    page.route("**/api/runs*", lambda route: held.append(route))  # hold the runs answer until the panel is open
    page.emulate_media(color_scheme="dark")
    page.goto(URL + "/#/stewardiq")
    sec = page.locator("section.hub-process", has=page.get_by_role("heading", name="Engage and escalate"))
    btn = sec.locator("button.hub-step").nth(1)
    btn.click()
    assert btn.get_attribute("aria-expanded") == "true"
    for r in held:
        r.continue_()
    page.unroute("**/api/runs*")
    page.wait_for_selector("section.hub-process .hub-process-state")  # the first runs answer has landed
    assert sec.locator(".hub-process-state .hub-mark-idle").count() == 1  # the seed has no runs for this process
    assert _panel(sec).is_visible()  # not hidden inside a fold that closed under it
    assert sec.locator("button.hub-step").nth(1).get_attribute("aria-expanded") == "true"
    assert sec.locator("button.hub-step").nth(1).evaluate("e => e === document.activeElement")
