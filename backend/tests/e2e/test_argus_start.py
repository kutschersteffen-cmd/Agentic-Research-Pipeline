"""Argus start page (#/argus) against the running app; the second test stubs runs and review items."""

import os

import pytest

from arp.config import Settings

URL = os.environ.get("ARP_E2E_URL")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(10_000)
        page.console_errors = []
        page.on("console", lambda m: m.type == "error" and page.console_errors.append(m.text))
        yield page
        browser.close()


def test_argus_start_page_shows_flow_runs_and_waiting(page):
    page.goto(URL + "/#/argus")
    page.wait_for_load_state("networkidle")
    assert page.get_by_role("button", name="Start new extraction").is_visible()
    tiles = page.get_by_role("region", name="Process").get_by_role("link")
    assert tiles.count() == 5
    assert [t.inner_text().split("\n")[0] for t in tiles.all()] == ["1 Companies", "2 Documents", "3 Schema", "4 Extract", "5 Results"]
    assert page.get_by_role("table", name="Runs").is_visible()
    assert page.get_by_role("complementary", name="Waiting for you").is_visible()
    assert not page.get_by_label("Only mine").is_checked()
    assert page.get_by_role("link", name="XBRL Facts").get_attribute("href") == "#/xbrl"
    assert page.console_errors == []


def _run(run_id, run_type, status, created_at, started_by, review_count=0, params=None):
    return {"run_id": run_id, "run_type": run_type, "status": status, "created_at": created_at, "updated_at": created_at,
            "params": {"started_by": started_by, **(params or {})}, "company_count": 3, "completed_count": 0, "failed_count": 0,
            "review_count": review_count, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0}


def test_runs_filter_by_step_and_only_mine(page):
    runs = [
        _run("r1", "extraction", "running", "2026-10-01T10:00:00Z", "dev", params={"schema_name": "Green capex", "schema_version": "s:v2"}),
        _run("r2", "extraction", "completed", "2026-10-02T10:00:00Z", "u-2", review_count=2,
             params={"schema_name": "Green capex", "schema_version": "s:v3", "started_by_name": "Bob Lee"}),
        _run("t1", "theme", "completed", "2026-10-03T10:00:00Z", "dev"),
    ]
    items = [{"item_key": k, "kind": "value", "run_id": rid, "run_type": "extraction", "payload": {}, "state": "pending",
              "escalated": False, "high_risk": False, "decision": None} for k, rid in (("a", "r2"), ("b", "r2"), ("c", "stewardiq_run"))]
    page.route("**/api/runs*", lambda route: route.fulfill(json={"runs": runs}))
    page.route("**/api/review/items*", lambda route: route.fulfill(json={"items": items}))
    page.route("**/api/argus/flows", lambda route: route.fulfill(json={"flows": []}))  # drafts other tests left behind
    page.goto(URL + "/#/argus")
    table = page.get_by_role("table", name="Runs")
    table.get_by_text("Green capex v3").wait_for()

    def listed():
        return [r.inner_text().split("\n")[0].strip() for r in table.locator("tbody tr").all()]

    assert listed() == ["Green capex v3", "Green capex v2"]
    rows = table.locator("tbody tr")
    assert "3 companies" in rows.nth(0).inner_text() and "5 Results" in rows.nth(0).inner_text() and "Bob Lee" in rows.nth(0).inner_text()
    assert "Needs you" in rows.nth(0).inner_text() and "4 Extract" in rows.nth(1).inner_text() and "Running" in rows.nth(1).inner_text()

    waiting = page.get_by_role("complementary", name="Waiting for you")
    assert "Values to review: 2" in waiting.inner_text()
    assert waiting.get_by_role("link").get_attribute("href") == "#/review"
    tiles = page.get_by_role("region", name="Process").get_by_role("link")
    assert "2 values need you" in tiles.nth(4).inner_text()
    assert [("argus-tile-await" in (t.get_attribute("class") or "")) for t in tiles.all()] == [False] * 4 + [True]

    tiles.nth(3).click()
    assert listed() == ["Green capex v2"]
    tiles.nth(3).click()
    assert listed() == ["Green capex v3", "Green capex v2"]

    page.get_by_label("Only mine").check()
    assert listed() == ["Green capex v2"]
    assert "Values to review" not in waiting.inner_text()
    assert page.console_errors == []
