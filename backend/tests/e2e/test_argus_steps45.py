"""Argus steps 4 Extract and 5 Results (#/argus/<flow_id>/4 and /5) against the running app.

The run is seeded straight into the stack's store (no model call), so this runs on CI's key-less stack."""

import json
import os
import re
import shutil
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from arp.argus.flows import FlowStore
from arp.config import Settings
from arp.schemas.common import CompanyRef, JobStatus, RunManifest
from arp.storage.run_store import RunStore
from tests.pdf_fixtures import FILLER, make_pdf

URL = os.environ.get("ARP_E2E_URL")
API = os.environ.get("ARP_E2E_API_URL", "http://127.0.0.1:8000")  # the stack's API (e2e_stack.sh)
DSN = os.environ.get("ARP_POSTGRES_DSN", "postgresql+psycopg://arp:arp@localhost:5432/arp_test")  # e2e_stack.sh's default
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

TAG = uuid4().hex[:6]
A, B, C = f"apple{TAG}", f"micro{TAG}", f"sap{TAG}"


def _field(fid, name, value, route, *, state="found", page=None):
    cites = [{"doc_id": "d1", "doc_type": "10-K", "quote": "Green capex was 12", "grounded": True, "page": page,
              "company_id": A, "source_filename": "a.pdf"}] if page else []
    return {"field_id": fid, "field_name": name, "value": value, "citations": cites, "confidence": 0.9, "grounded": True,
            "conflicting_sources": False, "value_state": state, "route": route, "period_end": "2025-12-31"}


@pytest.fixture
def seeded(tmp_path):
    settings = Settings()
    store = RunStore(DSN, settings.runs_dir)
    run_id = f"extraction_e2e{uuid4().hex[:8]}"  # one run per test: Retry changes it
    store.save_manifest(RunManifest(run_id=run_id, run_type="extraction", status=JobStatus.PARTIALLY_COMPLETED, company_count=3,
                                    completed_count=1, failed_count=1, estimated_cost_usd=0.42, created_at=(datetime.now(UTC) - timedelta(minutes=10)).isoformat(),
                                    params={"schema_name": "Green capex", "schema_version": "sch_g:v1"}))
    names = {A: "Applewood", B: "Microwood", C: "Sapwood"}
    store.save_companies(run_id, [CompanyRef(company_id=k, name=v) for k, v in names.items()])  # resumable, as a real run is
    (store.run_dir(run_id) / "start_request.json").write_text(json.dumps(
        {"profile": "custom", "companies": [{"company_id": k, "name": v} for k, v in names.items()]}))
    issuer = f"k{TAG}"
    fields = [
        _field("capex", "Green capex", 12, "review", page=1),
        _field("target", "Green capex target", None, "review", state="not_found"),
        _field("total", "Total capex", 40, "auto_accept", page=1),
    ]
    store.append_result(run_id, {"_key": A, "company_id": A, "name": "Applewood", "issuer_key": issuer, "schema_id": "sch_g",
                                 "run_id": run_id, "overall_confidence": 0.9, "needs_review": True, "fields": fields})
    for f in fields[:2]:
        store.append_review_item(run_id, {"item_key": f"{issuer}:{f['field_id']}:2025-12-31", "company_id": A, "issuer_key": issuer,
                                          "field_id": f["field_id"], "period_end": "2025-12-31", "field": f})
    store.append_error(run_id, {"key": B, "error": "No text could be read from scan.pdf", "document_problem": True})
    docs = settings.documents_dir / A / "10-K"
    docs.mkdir(parents=True, exist_ok=True)
    make_pdf(docs / "a.pdf", ["Applewood Annual Report 2025\nGreen capex was 12", FILLER], n_pages=2)  # the quote on page 1
    flows = FlowStore(settings.runs_dir / "_flows")
    from arp.api.auth import Principal

    flow = flows.create(Principal(user_id="dev", name="dev", role="approver"))
    flows.update(flow.flow_id, lambda f: (setattr(f, "run_id", run_id), setattr(f, "step", 4)))
    yield flow.flow_id
    shutil.rmtree(settings.documents_dir / A, ignore_errors=True)


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


def test_step_4_shows_each_company_and_what_to_do_about_a_failure(page, seeded):
    page.goto(f"{URL}/#/argus/{seeded}/4")
    line = page.get_by_role("status").filter(has_text="Started")
    # the seeded run is over, so no time left is shown; the running form is checked in tests/argusFlow.test.ts (AC-39)
    assert re.fullmatch(r"Started \d\d:\d\d · 2 of 3 done · \$0\.42 so far", line.inner_text())
    table = page.get_by_role("table", name="Companies in this run")
    rows = {r.locator("td").first.inner_text(): r for r in table.locator("tbody tr").all()}
    assert "Done" in rows["Applewood"].inner_text() and "Stopped" in rows["Sapwood"].inner_text()  # AC-72
    failed = rows["Microwood"]
    assert "Failed" in failed.inner_text() and "No text could be read from scan.pdf" in failed.inner_text()  # AC-37
    assert failed.get_by_role("button", name="Retry").is_enabled() and failed.get_by_role("link", name="Replace file").count() == 1
    assert table.get_by_role("progressbar").count() == 3
    assert page.console_errors == []


def test_step_5_lists_values_with_what_needs_you_first(page, seeded):
    page.goto(f"{URL}/#/argus/{seeded}/5")
    table = page.get_by_role("table", name="Extracted values")
    table.locator("tbody tr").first.wait_for()
    rows = table.locator("tbody tr")
    assert rows.count() == 3  # AC-40
    first, second, third = rows.nth(0), rows.nth(1), rows.nth(2)
    for name in ("Approve", "Edit", "Reject"):
        assert first.get_by_role("button", name=name).count() == 1
    for name in ("Confirm not disclosed", "Enter value"):  # AC-42
        assert second.get_by_role("button", name=name).count() == 1
    assert "No review needed" in third.inner_text()
    page.get_by_label("Only what needs me").check()
    assert rows.count() == 2  # AC-41
    page.get_by_label("Only what needs me").uncheck()
    third.get_by_role("button", name="p. 1").click()  # AC-43: the cited page, the quote boxed on it
    page.locator(".source-panel .source-page-img").wait_for()
    page.locator(".source-panel .source-page-box").first.wait_for()
    assert page.get_by_role("link", name="Download CSV").count() == 1
    assert page.console_errors == []


def test_retry_takes_a_failed_company_out_of_failed_and_never_strands_it(page, seeded):
    page.goto(f"{URL}/#/argus/{seeded}/4")
    row = page.get_by_role("table", name="Companies in this run").locator("tbody tr").filter(has_text="Microwood")
    with page.expect_response(lambda r: r.url.endswith(f"/companies/{B}/retry")) as info:
        row.get_by_role("button", name="Retry").click()
    assert info.value.status == 200, info.value.text()  # not "503: no running event loop"
    statuses = {c["company_id"]: c["status"] for c in info.value.json()["companies"]}
    assert statuses[B] == "Waiting"  # AC-38: it leaves Failed at once
    api = page.request
    end = time.monotonic() + 30
    while _progress(api, seeded)["status"] in ("pending", "running"):
        assert time.monotonic() < end, "the retry never finished"
        time.sleep(0.5)
    # this stack's resume has no model (CI has no key) or no schema for the seeded run: the company fails again, its error back
    after = {c["company_id"]: c for c in _progress(api, seeded)["companies"]}[B]
    assert after["status"] == "Failed" and after["reason"], after  # never stranded as Stopped
    assert page.console_errors == []


def _progress(api, fid):
    r = api.get(f"{API}/api/argus/flows/{fid}/progress")
    assert r.ok, r.text()
    return r.json()


@pytest.fixture
def conflicted():
    """A finished run whose new Green capex (14) conflicts with an accepted 12 (data rule 1), seeded as the commit queues it."""
    settings = Settings()
    store = RunStore(DSN, settings.runs_dir)
    run_id = f"extraction_e2ec{uuid4().hex[:8]}"
    store.save_manifest(RunManifest(run_id=run_id, run_type="extraction", status=JobStatus.COMPLETED, company_count=1,
                                    completed_count=1, params={"schema_name": "Green capex", "schema_version": "sch_g:v1"}))
    issuer = f"c{TAG}"
    field = _field("capex", "Green capex", 14, "auto_accept")
    store.append_result(run_id, {"_key": A, "company_id": A, "name": "Applewood", "issuer_key": issuer, "schema_id": "sch_g",
                                 "run_id": run_id, "overall_confidence": 0.9, "needs_review": True, "fields": [field]})
    store.append_review_item(run_id, {"item_key": f"{issuer}:capex:2025-12-31", "company_id": A, "issuer_key": issuer,
                                      "field_id": "capex", "period_end": "2025-12-31", "field": field, "kind": "conflict",
                                      "new_value": 14, "accepted": {"value": 12, "fact_id": 1, "status": "approved"}})
    flows = FlowStore(settings.runs_dir / "_flows")
    from arp.api.auth import Principal

    flow = flows.create(Principal(user_id="dev", name="dev", role="approver"))
    flows.update(flow.flow_id, lambda f: (setattr(f, "run_id", run_id), setattr(f, "step", 5)))
    return flow.flow_id


def test_step_5_shows_a_conflict_as_accepted_and_new(page, conflicted):  # AC-55
    page.goto(f"{URL}/#/argus/{conflicted}/5")
    table = page.get_by_role("table", name="Extracted values")
    row = table.locator("tbody tr").first
    row.wait_for()
    value = row.locator("td[data-label='Value']").inner_text()
    assert "Accepted: 12" in value and "New: 14" in value
    for name in ("Keep accepted", "Accept new"):
        assert row.get_by_role("button", name=name).count() == 1
    assert row.get_by_role("button", name="Edit").count() == 0
    assert page.console_errors == []


def test_leaving_results_with_the_source_text_open_keeps_the_app_alive(page, seeded):
    """Seen live 3 of 3 times: after "Show in source", leaving the page blanked the whole app. scrollIntoView()
    returns a promise in current Chrome; returned from an effect, React calls it as the clean-up."""
    text = "Applewood Annual Report 2025\nGreen capex was 12"
    span = {"doc_id": "d1", "doc_type": "10-K", "title": "Annual report", "company_id": None, "source_filename": None, "page": 1,
            "quote": "Green capex was 12", "char_start": 29, "char_end": 47, "page_start": 0, "page_text": text}

    def with_evidence(route):  # the seeded run has no stored page text: give the item one cited span
        response = route.fetch()
        route.fulfill(response=response, json={**response.json(), "evidence": [span]})

    page.route("**/api/review/runs/*/items/*/context", with_evidence)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{URL}/#/argus/{seeded}/5")
    table = page.get_by_role("table", name="Extracted values")
    table.locator("tbody tr").first.get_by_role("button", name="Review").click()
    page.get_by_role("button", name="Show in source").first.click()
    page.locator(".source-panel .source-text mark").wait_for()  # the cited text, scrolled into view
    page.evaluate("location.hash = '#/history'")
    page.get_by_role("heading", name="Run History").wait_for()
    assert errors == []
