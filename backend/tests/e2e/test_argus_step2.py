"""Argus step 2 Documents (#/argus/<flow_id>/2) against the running app."""

import os
import re

import pytest

from arp.config import Settings
from tests.pdf_fixtures import FILLER, make_pdf

URL = os.environ.get("ARP_E2E_URL")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

CSV = ("name,lei,isin,sector,country\n"
       "Apple Inc,HWUPKR0MPOU8FGXBT394,US0378331005,Information Technology,US\n"
       "Microsoft Corporation,INR2EJN1ERAN0W5ZP974,US5949181045,Information Technology,US\n"
       "SAP SE,529900D6BF99LW9R2E68,,Information Technology,DE\n")


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(15_000)
        page.console_errors = []
        page.on("console", lambda m: m.type == "error" and page.console_errors.append(m.text))
        yield page
        browser.close()


def test_step_2_checks_an_upload_and_keeps_it_across_a_reload(page, tmp_path):
    page.goto(URL + "/#/argus")
    page.get_by_role("button", name="Start new extraction").click()
    page.wait_for_url(re.compile(r"#/argus/[0-9a-f]{32}/1$"))
    csv = tmp_path / "u.csv"
    csv.write_text(CSV)
    page.locator('input[type="file"]').set_input_files(str(csv))
    page.get_by_role("table", name="Companies").get_by_text("SAP SE").wait_for()
    page.get_by_role("button", name="Continue with 3 companies").click()
    page.wait_for_url(re.compile(r"/2$"))
    page.locator("#argus-reporting-year").fill("2025")
    page.locator("#argus-reporting-year").blur()
    page.get_by_label("I upload them").check()
    good = make_pdf(tmp_path / "apple-2025.pdf", ["Apple Inc Annual Report 2025", FILLER], n_pages=2)
    bad = make_pdf(tmp_path / "apple-other.pdf", ["Microsoft Corporation Annual Report 2025", FILLER], n_pages=2)
    files = page.get_by_role("table", name="Files")
    for path in (good, bad):
        page.get_by_label("Apple Inc", exact=True).set_input_files(str(path))
        files.get_by_text(path.name).wait_for()
    assert "✓ Apple Inc, 2025" in files.locator("tr", has_text="apple-2025.pdf").inner_text()
    other = files.locator("tr", has_text="apple-other.pdf")
    assert "Company not found in document" in other.inner_text() and "argus-row-await" in other.get_attribute("class")
    page.get_by_role("button", name="Keep all that pass").click()
    page.get_by_role("button", name="Continue with 1 file for 1 company").wait_for()
    assert "Kept" in files.locator("tr", has_text="apple-2025.pdf").inner_text()
    page.get_by_role("button", name="apple-2025.pdf").hover()
    page.get_by_role("img", name="First page of apple-2025.pdf").wait_for()
    page.get_by_role("button", name="apple-2025.pdf").click()
    page.locator(".source-panel").wait_for()
    page.reload()
    page.get_by_role("button", name="Continue with 1 file for 1 company").wait_for()
    assert page.locator('[role="tablist"]').count() == 0
    bar = page.get_by_role("navigation", name="Steps")
    assert bar.get_by_role("listitem").nth(1).get_attribute("aria-current") == "step"
    assert bar.get_by_role("link", name="1 Companies").count() == 1
    assert page.console_errors == []
