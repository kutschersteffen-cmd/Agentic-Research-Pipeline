"""Argus step 3 Schema (#/argus/<flow_id>/3) against the running app."""

import os
import re
from uuid import uuid4

import pytest

from arp.config import Settings
from tests.pdf_fixtures import FILLER, make_pdf

URL = os.environ.get("ARP_E2E_URL")
API = os.environ.get("ARP_E2E_API_URL", "http://127.0.0.1:8000")  # the stack's API (e2e_stack.sh)
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

TAG = uuid4().hex[:6]
APPLE = f"Applewood {TAG}"
SCHEMA = f"Green capex {TAG}"


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


def _ok(r):
    assert r.ok, r.text()
    return r.json()


def test_step_3_shows_the_fields_and_starts_a_trial(page, tmp_path):
    api = page.request
    fid = _ok(api.post(API + "/api/argus/flows"))["flow_id"]
    _ok(api.post(f"{API}/api/argus/flows/{fid}/companies/upload",
                 multipart={"file": {"name": "u.csv", "mimeType": "text/csv", "buffer": f"name\n{APPLE}\n".encode()}}))
    cid = _ok(api.get(f"{API}/api/argus/flows/{fid}"))["companies"][0]["company_id"]
    _ok(api.patch(f"{API}/api/argus/flows/{fid}", data={"reporting_year": 2025, "step": 3}))
    pdf = make_pdf(tmp_path / "a.pdf", [f"{APPLE} Annual Report 2025", FILLER], n_pages=2).read_bytes()
    _ok(api.post(f"{API}/api/argus/flows/{fid}/documents/upload", multipart={
        "company_id": cid, "doc_type": "10-K", "file": {"name": "a.pdf", "mimeType": "application/pdf", "buffer": pdf}}))
    _ok(api.post(f"{API}/api/argus/flows/{fid}/files", data={"all_that_pass": True}))
    fields = [{"field_id": f"f{i}", "name": f"Field {i}", "description": f"Meaning {i}", "data_type": "number",
               "extraction_instructions": "Annual report"} for i in range(4)]
    _ok(api.post(API + "/api/extraction/schemas", data={"schema_id": f"sch_e2e_{TAG}", "name": SCHEMA, "fields": fields}))

    page.goto(f"{URL}/#/argus/{fid}/3")
    pick = page.get_by_role("region", name="What to extract")
    for heading in ("Saved schemas", "Templates", "Describe it in words"):
        pick.get_by_role("heading", name=heading).wait_for()
    for name in ("Transition plan", "Financials", "TNFD"):
        assert pick.get_by_role("button", name=re.compile(name, re.I)).count() >= 1  # AC-25
    assert page.locator("details.argus-settings").get_attribute("open") is None
    pick.get_by_role("button", name=re.compile(re.escape(SCHEMA))).click()
    table = page.get_by_role("table", name="Fields to extract")
    table.get_by_text("Meaning 3").wait_for()
    headers = table.locator("thead th").all_inner_texts()
    assert [h.strip().lower() for h in headers] == ["field", "type", "unit", "what it means", "look in"]  # AC-26
    assert table.locator("tbody tr").count() == 4
    start = page.get_by_role("button", name=f"Try {SCHEMA} on 1 company")  # AC-29
    start.click()
    # Starting scans earlier runs and launches the run, slower on a cold CI stack; an error the page shows fails fast.
    page.wait_for_function("() => location.hash === '#/argus' || document.querySelector('[role=alert]')", timeout=45_000)
    alert = page.locator("[role=alert]")
    assert not alert.count(), f"Start failed on the page: {alert.first.inner_text()}"
    assert page.evaluate("location.hash") == "#/argus"
    assert _ok(api.get(f"{API}/api/argus/flows/{fid}"))["run_id"]
    bar_step = _ok(api.get(f"{API}/api/argus/flows/{fid}"))["step"]
    assert bar_step == 4
    assert page.console_errors == []
