"""showcase-stewardship-fixes PR A, the "unit (browser)" rows: the running app with the named API routes stubbed."""

import os
import re

import httpx
import pytest

from arp.config import Settings

URL = os.environ.get("ARP_E2E_URL")
API = os.environ.get("ARP_E2E_API_URL", "http://127.0.0.1:8000")  # the stack's API (e2e_stack.sh)
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

RUN = {"run_id": "identity_failed1", "run_type": "identity", "created_at": "2026-11-11T09:00:00+00:00",
       "updated_at": "2026-11-11T09:05:00+00:00", "status": "partially_completed", "params": {}, "company_count": 2,
       "completed_count": 1, "failed_count": 1, "review_count": 0, "input_tokens": 0, "output_tokens": 0,
       "cache_read_tokens": 0, "cache_creation_tokens": 0, "estimated_cost_usd": 0.0, "batch_saved_usd": 0.0,
       "batch_wait": None, "model": None, "verifier_model": None, "error": None, "cancel_requested": False}


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(10_000)
        yield page
        browser.close()


def open_failure(page, company_errors):
    page.route(re.compile(r".*/api/runs(\?.*)?$"), lambda r: r.fulfill(json={"runs": [RUN]}))
    page.route("**/api/runs/identity_failed1/failure", lambda r: r.fulfill(json={
        "run_id": "identity_failed1", "status": "partially_completed", "error": None, "traceback": None,
        "company_errors": company_errors}))
    page.goto(f"{URL}/#/history")
    page.get_by_role("button", name="Details for identity_failed1").click()
    return page.locator(".failure-details")


def test_company_traceback_is_shown(page):  # AC-19
    details = open_failure(page, [{"key": "acme", "error": "ReadTimeout",
                                   "traceback": "Traceback (most recent call last): X"}])
    details.get_by_text("Traceback (most recent call last): X").wait_for()
    assert "acme" in details.inner_text()
    assert "No traceback was recorded for this run." not in details.inner_text()


def test_no_traceback_anywhere_says_so(page):  # AC-20 (must not change)
    details = open_failure(page, [{"key": "acme", "error": "ReadTimeout", "traceback": None}])
    details.get_by_text("No traceback was recorded for this run.").wait_for()


NOTE_OFF = ("Re-checking sources is switched off on this server, so a derivation uses only facts entered by hand and "
            "documents already stored. Cells without facts come out as Not rated.")


def with_refresh(enabled):
    """Pass the real answer through with `refresh_enabled` set."""
    def handler(route):
        body = route.fetch().json()
        route.fulfill(json={**body, "refresh_enabled": enabled})
    return handler


@pytest.mark.parametrize("enabled", [False, True])
def test_refresh_note_by_the_derive_buttons(page, enabled):  # AC-24, AC-25 (switch off), AC-27 (on)
    page.route("**/api/transition-barrier/matrix", with_refresh(enabled))
    page.route("**/api/transition-barrier/cells/STL-R1/European%20Union", with_refresh(enabled))
    page.goto(f"{URL}/#/transitionBarrier")
    page.get_by_role("button", name="STL-R1", exact=True).click()
    page.get_by_role("button", name="Derive all regions").wait_for()
    assert page.get_by_text(NOTE_OFF).count() == (0 if enabled else 1)
    page.goto(f"{URL}/#/transitionBarrier/cell/STL-R1/European%20Union")
    page.get_by_role("button", name="Derive this cell").wait_for()
    assert page.get_by_text(NOTE_OFF).count() == (0 if enabled else 1)


FLAG = {"source_run_id": "theme_1", "company_id": "ko", "activity_id": "act_dd5b90051fcd", "old_verdict": "include",
        "old_confidence": 0.8, "old_generated_at": "2026-02-01T00:00:00+00:00",
        "newest_document_at": "2026-03-01T00:00:00+00:00", "reason": "r"}


def calibration_cells(page, flag):
    page.route("**/api/calibration/runs", lambda r: r.fulfill(json={"run_id": "calibration_1"})
               if r.request.method == "POST" else r.fallback())
    page.route("**/api/calibration/runs/calibration_1/results*", lambda r: r.fulfill(json={"total": 1, "results": [flag]}))
    page.goto(f"{URL}/#/backgroundAgents")
    page.get_by_role("tab", name="Calibration Agent").click()
    page.get_by_role("button", name="Check now").click()
    page.get_by_role("button", name="Refresh results").click()
    row = page.locator("tr", has=page.get_by_text("theme_1", exact=True))
    row.wait_for()
    return row.locator("td").nth(1), row.locator("td").nth(2)


def test_calibration_flag_shows_names_then_ids(page):  # AC-38
    company, activity = calibration_cells(page, {**FLAG, "company_name": "Coca-Cola Co", "activity_name": "Soft drinks"})
    assert company.inner_text().split() == ["Coca-Cola", "Co", "ko"] and company.locator("span", has_text="ko").count() == 1
    assert activity.inner_text().split() == ["Soft", "drinks", "act_dd5b90051fcd"]
    assert activity.locator("span", has_text="act_dd5b90051fcd").count() == 1


def test_older_calibration_flag_shows_ids(page):  # AC-39
    company, activity = calibration_cells(page, FLAG)
    assert (company.inner_text(), activity.inner_text()) == ("ko", "act_dd5b90051fcd")


TP = "transition_plan_indicators"


def stub_flow(page, step, **changes):
    """A real (empty) flow from the stack, answered with `changes` applied."""
    flow = httpx.post(f"{API}/api/argus/flows").json()
    fid = flow["flow_id"]
    page.route(f"**/api/argus/flows/{fid}", lambda r: r.fulfill(json={**r.fetch().json(), "step": step, **changes})
               if r.request.method == "GET" else r.fallback())
    return fid


def test_step_3_states_time_and_cost_before_a_first_run(page):  # AC-56
    company = {"company_id": "acme", "entity_id": None, "name": "Acme", "ticker": None, "website": None, "cik": None,
               "lei": None, "isin": None, "country": None, "sector": None}
    fid = stub_flow(page, 3, companies=[company], schema_choice={"kind": "schema", "schema_id": TP, "version": 1, "profile": None},
                    files=[{"key": "acme/x/a.pdf", "company_id": "acme", "company_name": "Acme", "doc_type": "x", "filename": "a.pdf",
                            "year": 2025, "source": "upload", "check": "ok", "passes": True, "state": "kept", "content_key": "k"}])
    page.route(re.compile(r".*/api/runs\?run_type=extraction$"), lambda r: r.fulfill(json={"runs": []}))
    page.goto(f"{URL}/#/argus/{fid}/3")
    note = page.get_by_text("No earlier run of this template yet, so time and cost are not known. Try it on 1 company first: the run shows both.")
    note.wait_for()
    assert note.locator("xpath=..").get_by_role("button").count() >= 1  # in the row of the start button


def field(name, value, state="found"):
    return {"field_id": name, "field_name": name, "value": value, "citations": [], "confidence": 0.9, "grounded": True,
            "conflicting_sources": False, "value_state": state, "period_end": "2025-12-31"}


INDICATORS = [{"number": i, "identifier": ident, "category": "target", "walk_or_talk": kind, "question": f"Q {ident}?",
               "guideline": "", "options": ["Yes", "No"]}
              for i, (ident, kind) in enumerate([("A_headline_1", "walk"), ("W2", "walk"), ("W3", "walk"), ("T1", "talk"), ("T2", "talk")], 1)]


def step_5(page, schema_id, fields, decision=None):
    run_id = "extraction_tp1"
    fid = stub_flow(page, 5, run_id=run_id, schema_choice={"kind": "schema", "schema_id": schema_id, "version": 1, "profile": None})
    page.route(f"**/api/extraction/runs/{run_id}/results*", lambda r: r.fulfill(json={"total": 1, "results": [
        {"company_id": "acme", "name": "Acme", "schema_id": schema_id, "run_id": run_id, "fields": fields,
         "overall_confidence": 0.9, "needs_review": False, "generated_at": "2026-11-11T09:00:00+00:00"}]}))
    page.route("**/api/review/items?run_id=*", lambda r: r.fulfill(json={"items": []}))
    page.route(f"**/api/extraction/runs/{run_id}/review-decisions", lambda r: r.fulfill(json={"decisions": {}}))
    page.route(f"**/api/extraction/schemas/{schema_id}?version=1", lambda r: r.fulfill(json={
        "schema_id": schema_id, "version": 1, "name": "T", "description": "", "release_flag": True,
        "fields": [{"field_id": f["field_id"], "name": f["field_name"], "description": "Has the company set a net-zero target?"
                    if f["field_name"] == "A_headline_1" else "Revenue in USD.", "data_type": "boolean", "unit": None,
                    "extraction_instructions": "", "required": False, "source_doc_types": [], "seed_keywords": []} for f in fields]}))
    page.route("**/api/transition-plan/indicators", lambda r: r.fulfill(json=INDICATORS))
    page.route(f"**/api/runs/{run_id}", lambda r: r.fulfill(json={**RUN, "run_id": run_id, "run_type": "extraction", "status": "completed"}))
    page.route(f"**/api/decision/runs/{run_id}/decision", decision or (lambda r: r.fulfill(
        status=404, json={"detail": "No scoring template is attached to this run."})))
    page.route("**/api/decision/templates/match", lambda r: r.fulfill(json=[]))
    page.goto(f"{URL}/#/argus/{fid}/5")
    table = page.get_by_role("table", name="Extracted values")
    table.locator("tbody tr").first.wait_for()
    return table


TP_FIELDS = [field("A_headline_1", True), field("W2", True), field("W3", False), field("T1", True),
             field("T2", None, "not_found"), field("capex_total", 5)]


def test_step_5_field_cell_holds_the_question_then_the_id(page):  # AC-57
    cell = step_5(page, TP, TP_FIELDS).locator("tbody tr", has_text="A_headline_1").locator("td").nth(1)
    assert cell.inner_text().split("A_headline_1")[0].strip() == "Has the company set a net-zero target?"
    assert cell.locator("span.mono", has_text="A_headline_1").count() == 1


def test_step_5_walk_and_talk_line(page):  # AC-58
    step_5(page, TP, TP_FIELDS)
    page.get_by_text("Disclosed 3 of 5 · Walk 2 of 3 · Talk 1 of 2").wait_for()


def test_step_5_scoring_shows_score_and_tier(page):  # AC-59
    decision = {"framework": {"name": "TP scoring", "version": 1}, "run_status": "completed", "scored_at": None,
                "missing_columns": [], "level_scale": None,
                "result": {"tier_summary": [], "excluded_count": 0, "insufficient_count": 0, "entities": [
                    {"entity_key": "acme", "name": "Acme", "rank": 1, "score": 62.5, "tier_name": "Tier 2", "tier_action": "",
                     "status": "scored", "notes": []}]}}
    step_5(page, TP, TP_FIELDS, decision=lambda r: r.fulfill(json=decision))
    section = page.locator("section.card", has=page.get_by_role("heading", name="Scoring"))
    row = section.locator("tr", has_text="Acme")
    row.wait_for()
    assert "62.5" in row.inner_text() and "Tier 2" in row.inner_text()


def test_step_5_scoring_without_template_offers_the_picker(page):  # AC-60
    step_5(page, TP, TP_FIELDS)
    section = page.locator("section.card", has=page.get_by_role("heading", name="Scoring"))
    section.get_by_role("button", name="Score this run").wait_for()
    assert "No scoring template is attached" not in section.inner_text()


def test_step_5_other_template_field_cell_unchanged(page):  # AC-61 (must not change)
    cell = step_5(page, "sch_other", [field("revenue", 5)]).locator("tbody tr").first.locator("td").nth(1)
    assert cell.inner_text() == "revenue"


def test_criterion_detail_comes_into_view_with_focus(page):  # AC-62 (checked by the evaluator too)
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{URL}/#/transitionBarrier")
    page.get_by_role("button", name="STL-R1", exact=True).click()
    heading = page.get_by_role("heading", name=re.compile(r"^STL-R1 — "))
    heading.wait_for()
    page.wait_for_timeout(300)
    box = heading.bounding_box()
    assert box["y"] >= 0 and box["y"] + box["height"] <= 800
    assert heading.evaluate("h => document.activeElement === h")
