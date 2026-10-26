"""Argus step 1 Companies (#/argus/<flow_id>/1) against the running app."""

import os
import re

import pytest

from arp.config import Settings

URL = os.environ.get("ARP_E2E_URL")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

CSV = ("name,lei,isin,cik,sector,country\n"
       "Apple,HWUPKR0MPOU8FGXBT394,US0378331005,0000320193,Information Technology,US\n"
       "Microsoft,,US5949181045,,Information Technology,US\n"
       "SAP,529900D6BF99LW9R2E68,,,Information Technology,DE\n"
       "Acme,,,,,\n")


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


def _new_flow(page):
    page.goto(URL + "/#/argus")
    page.get_by_role("button", name="Start new extraction").click()
    page.wait_for_url(re.compile(r"#/argus/[0-9a-f]{32}/1$"))
    page.get_by_role("table", name="Companies").wait_for()
    return page.url.split("#/argus/")[1].split("/")[0]


def _names(page):
    return [r.locator(".xbrl-name").text_content() for r in page.get_by_role("table", name="Companies").locator("tbody tr").all()]


def test_start_new_extraction_opens_empty_step_1_and_lists_a_draft(page):
    flow_id = _new_flow(page)
    bar = page.get_by_role("navigation", name="Steps").get_by_role("listitem")
    assert [i.inner_text() for i in bar.all()] == ["1 Companies", "2 Documents", "3 Schema", "4 Extract", "5 Results"]
    assert bar.nth(0).get_attribute("aria-current") == "step"
    assert _names(page) == []
    assert page.locator('[role="tablist"]').count() == 0
    assert page.get_by_role("navigation", name="Steps").count() == 1
    page.goto(URL + "/#/argus")
    row = page.get_by_role("table", name="Runs").locator("tbody tr").filter(has=page.locator(f'a[href="#/argus/{flow_id}/1"]'))
    row.wait_for()
    assert "Draft" in row.inner_text() and "1 Companies" in row.inner_text() and "New extraction" in row.inner_text()
    assert page.console_errors == []


def test_upload_shows_rows_and_survives_reload(page, tmp_path):
    _new_flow(page)
    path = tmp_path / "universe.csv"
    path.write_text(CSV)
    page.locator('input[type="file"]').set_input_files(str(path))
    table = page.get_by_role("table", name="Companies")
    table.get_by_text("Acme").wait_for()
    assert _names(page) == ["Apple", "Microsoft", "SAP", "Acme"]
    rows = table.locator("tbody tr")
    for i, country in ((0, "US"), (1, "US"), (2, "DE")):
        text = rows.nth(i).inner_text()
        assert re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", text, re.I) and "Information Technology" in text and country in text
        assert "argus-row-await" not in (rows.nth(i).get_attribute("class") or "")
    assert "ISIN US0378331005" in rows.nth(0).inner_text() and "LEI HWUPKR0MPOU8FGXBT394" in rows.nth(0).inner_text()
    assert "argus-row-await" in rows.nth(3).get_attribute("class")
    assert "No identifier: add an ISIN, LEI or CIK" in rows.nth(3).inner_text()
    assert page.get_by_role("button", name="Continue with 4 companies").is_enabled()
    page.reload()
    table.get_by_text("Acme").wait_for()
    assert _names(page) == ["Apple", "Microsoft", "SAP", "Acme"]
    assert page.console_errors == []


def test_resolve_identities_starts_one_run_for_the_unmatched(page, tmp_path):
    calls = []

    def identity(route):
        calls.append(route.request.post_data_json)
        route.fulfill(json={"run_id": "id-run-1", "company_count": len(route.request.post_data_json["companies"])})

    page.route("**/api/identity/runs", identity)
    _new_flow(page)
    path = tmp_path / "universe.csv"
    path.write_text(CSV)
    page.locator('input[type="file"]').set_input_files(str(path))
    page.get_by_role("table", name="Companies").get_by_text("Acme").wait_for()
    assert calls == []
    page.get_by_role("button", name="Resolve identities").click()
    page.get_by_text("Identity run started").wait_for()
    assert [[c["name"] for c in body["companies"]] for body in calls] == [["Acme"]]
    assert page.get_by_role("link", name="Open identity runs").get_attribute("href") == "#/history"
    page.reload()
    page.get_by_text("Identity run started").wait_for()
    assert page.get_by_role("button", name="Resolve identities").count() == 0


def test_unknown_flow_says_so(page):
    page.goto(URL + "/#/argus/" + "0" * 32 + "/1")
    page.get_by_text("This extraction does not exist.").wait_for()
    assert page.get_by_role("link", name="Back to Argus").get_attribute("href") == "#/argus"
    # the browser logs the 404 response itself; nothing else may error
    assert [e for e in page.console_errors if "Failed to load resource" not in e] == []
