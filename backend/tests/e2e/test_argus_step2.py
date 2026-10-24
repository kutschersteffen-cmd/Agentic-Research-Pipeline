"""Argus step 2 Documents (#/argus/<flow_id>/2) against the running app."""

import os
import re
import uuid
from datetime import date

import pytest

from arp.config import Settings
from tests.pdf_fixtures import make_pdf

URL = os.environ.get("ARP_E2E_URL")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

CSV = ("name,lei,isin,sector,country\n"
       "Apple Inc.,HWUPKR0MPOU8FGXBT394,US0378331005,Information Technology,US\n"
       "Microsoft Corporation,,US5949181045,Information Technology,US\n"
       "SAP SE,529900D6BF99LW9R2E68,,Information Technology,DE\n")


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


def _step2(page, tmp_path):
    page.goto(URL + "/#/argus")
    page.get_by_role("button", name="Start new extraction").click()
    page.wait_for_url(re.compile(r"#/argus/[0-9a-f]{32}/1$"))
    (tmp_path / "u.csv").write_text(CSV)
    page.locator('input[type="file"]').set_input_files(str(tmp_path / "u.csv"))
    page.get_by_role("button", name="Continue with 3 companies").click()
    page.wait_for_url(re.compile(r"#/argus/[0-9a-f]{32}/2$"))
    page.get_by_role("table", name="Files").wait_for()
    year = page.get_by_label("Reporting year")
    year.fill("2025")
    year.press("Enter")
    return page.url.split("#/argus/")[1].split("/")[0]


def _pdfs(tmp_path, specs):
    """specs: (file name, text); a random token keeps each run's PDFs distinct from earlier runs' files."""
    out = []
    for name, text in specs:
        out.append(str(make_pdf(tmp_path / name, [f"{text} {uuid.uuid4().hex}"], n_pages=1)))
    return out


def _upload(page, paths, company="Apple Inc."):
    page.locator("#argus-doc-company").select_option(label=company)
    rows = page.get_by_role("table", name="Files").locator("tbody tr")
    before = rows.count()
    page.get_by_label("Upload PDFs").set_input_files(paths)
    page.wait_for_function(f"document.querySelectorAll('table[aria-label=Files] tbody tr').length >= {before + len(paths)}")


def _col(page, label):
    return [c.inner_text() for c in page.get_by_role("table", name="Files").locator(f'td[data-label="{label}"]').all()]


def _continue(page):
    return page.get_by_role("button", name=re.compile(r"^Continue with \d+ files? for"))


def _docs_on_file(page, flow_id):
    page.goto(f"{URL}/#/argus/{flow_id}/1")
    table = page.get_by_role("table", name="Companies")
    table.get_by_text("SAP SE").wait_for()
    return [c.inner_text() for c in table.locator('td[data-label="Documents on file"]').all()]


def test_continue_opens_step_2_with_previous_year(page, tmp_path):
    page.goto(URL + "/#/argus")
    page.get_by_role("button", name="Start new extraction").click()
    page.wait_for_url(re.compile(r"#/argus/[0-9a-f]{32}/1$"))
    (tmp_path / "u.csv").write_text(CSV)
    page.locator('input[type="file"]').set_input_files(str(tmp_path / "u.csv"))
    page.get_by_role("button", name="Continue with 3 companies").click()
    page.wait_for_url(re.compile(r"#/argus/[0-9a-f]{32}/2$"))
    assert page.get_by_label("Reporting year").input_value() == str(date.today().year - 1)
    bar = page.get_by_role("navigation", name="Steps")
    assert bar.count() == 1 and bar.get_by_role("listitem").nth(1).get_attribute("aria-current") == "step"
    assert page.locator('[role="tablist"]').count() == 0
    assert page.get_by_role("radio", name="From the import folder").is_disabled()
    assert [r.inner_text() for r in page.locator(".argus-source").all()][0] == "I upload them"
    assert page.console_errors == []


def test_checks_keep_all_that_pass_and_remove_all(page, tmp_path):
    flow_id = _step2(page, tmp_path)
    before = _docs_on_file(page, flow_id)
    page.goto(f"{URL}/#/argus/{flow_id}/2")
    page.get_by_role("table", name="Files").wait_for()
    passing = [(f"2025_a{i}.pdf", "Apple Inc. annual report 2025") for i in range(7)]
    _upload(page, _pdfs(tmp_path, [*passing, ("2025_ms.pdf", "Microsoft Corporation annual report 2025"),
                                   ("2023_report.pdf", "Apple Inc. report 2023")]))
    checks = _col(page, "Check")
    assert checks[7:] == ["Company not found in document", "Year 2023, expected 2025"]
    rows = page.get_by_role("table", name="Files").locator("tbody tr")
    assert all("argus-row-await" in rows.nth(i).get_attribute("class") for i in (7, 8))
    page.get_by_role("button", name="Remove all").click()
    page.wait_for_function("[...document.querySelectorAll('.argus-state')].filter(e => e.textContent === 'Removed').length === 9")
    assert _continue(page).is_disabled()
    page.get_by_role("button", name="Keep all that pass").click()
    _continue(page).filter(has_text="Continue with 7 files for 1 company").wait_for()
    states = [s.split("\n")[0] for s in _col(page, "Decision")]
    assert states[:7] == ["Kept"] * 7 and states[7:] == ["Removed", "Removed"]
    assert _docs_on_file(page, flow_id) == before
    assert page.console_errors == []


def test_failing_files_start_undecided_and_remove_one_survives_reload(page, tmp_path):
    flow_id = _step2(page, tmp_path)
    _upload(page, _pdfs(tmp_path, [("2025_a.pdf", "Apple Inc. annual report 2025"), ("2025_b.pdf", "Apple Inc. sustainability 2025")]))
    _upload(page, _pdfs(tmp_path, [("2025_m.pdf", "Microsoft Corporation annual report 2025")]), company="Microsoft Corporation")
    _upload(page, _pdfs(tmp_path, [("2025_s.pdf", "Microsoft annual report 2025")]), company="SAP SE")
    assert _col(page, "Decision")[3].startswith("Keep")  # no state word: waits for a person
    _continue(page).filter(has_text="Continue with 3 files for 2 companies").wait_for()
    page.get_by_role("table", name="Files").locator("tbody tr").nth(1).get_by_role("button", name="Remove").click()
    _continue(page).filter(has_text="Continue with 2 files for 2 companies").wait_for()
    page.reload()
    page.get_by_role("table", name="Files").locator("tbody tr").nth(3).wait_for()
    assert _col(page, "Decision")[1].startswith("Removed")
    assert _continue(page).inner_text() == "Continue with 2 files for 2 companies"


def test_hover_shows_first_page_and_click_opens_side_panel(page, tmp_path):
    _step2(page, tmp_path)
    _upload(page, _pdfs(tmp_path, [("2025_10-K.pdf", "Apple Inc. annual report 2025")]))
    name = page.get_by_role("table", name="Files").get_by_role("button", name=re.compile(r"^2025_10-K(-\d+)?\.pdf$"))
    stored = name.inner_text()  # 2025_10-K-<n>.pdf when an earlier run left one on Apple
    name.hover()
    page.get_by_role("img", name=f"First page of {stored}").wait_for()
    name.click()
    page.locator(".source-panel h3").filter(has_text=stored).wait_for()
    page.locator(".source-panel iframe").wait_for()
    assert page.console_errors == []


def test_duplicate_upload_row(page, tmp_path):
    _step2(page, tmp_path)
    [path] = _pdfs(tmp_path, [("2025_a.pdf", "Apple Inc. annual report 2025")])
    _upload(page, [path])
    _upload(page, [path])
    stored = _col(page, "File")[0]  # 2025_a-<n>.pdf when an earlier run left a 2025_a.pdf on Apple
    assert _col(page, "Check") == ["✓ name, year", f"Duplicate of {stored}, skipped"]
    assert _continue(page).inner_text() == "Continue with 1 file for 1 company"
