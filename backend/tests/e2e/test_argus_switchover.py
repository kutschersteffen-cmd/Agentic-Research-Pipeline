"""Argus switch-over (slice 6): old routes and hand-overs land in the new flow, against the running app."""

import os
import re

import pytest

from arp.config import Settings

URL = os.environ.get("ARP_E2E_URL")
API = os.environ.get("ARP_E2E_API_URL", "http://127.0.0.1:8000")  # the stack's API (e2e_stack.sh)
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

STEP_1 = re.compile(r"#/argus/([0-9a-f]{32})/1$")


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


def _flow_count(page) -> int:
    return len(_ok(page.request.get(API + "/api/argus/flows"))["flows"])


def _lands_on_new_step_1(page, route: str) -> str:
    before = _flow_count(page)
    page.goto(f"{URL}/#/{route}")
    page.wait_for_url(STEP_1)
    page.get_by_text("Add one company").first.wait_for()
    assert _flow_count(page) == before + 1, f"{route} must create exactly one flow"
    return STEP_1.search(page.url).group(1)


def test_old_extraction_routes_land_on_the_argus_start_page(page):  # AC-62
    for route in ("extraction/companies/auto", "extraction"):
        page.goto(f"{URL}/#/{route}")
        page.wait_for_function("() => location.hash === '#/argus'")
        page.get_by_role("button", name="Start new extraction").wait_for()
        assert page.evaluate("location.hash") == "#/argus"
    assert page.console_errors == []


def test_universe_identify_and_documents_open_step_1_of_a_new_flow(page):  # AC-63
    for route in ("argusUniverse", "identity", "discovery"):
        _lands_on_new_step_1(page, route)
    assert page.console_errors == []


def test_transition_plan_opens_step_1_with_the_template_preselected(page):  # AC-64
    fid = _lands_on_new_step_1(page, "transitionPlan")
    choice = _ok(page.request.get(f"{API}/api/argus/flows/{fid}"))["schema_choice"]
    assert (choice["kind"], choice["schema_id"]) == ("schema", "transition_plan_indicators")
    page.goto(f"{URL}/#/argus/{fid}/3")
    heading = page.get_by_role("heading", name=re.compile("Transition plan", re.I)).first
    heading.wait_for()
    assert "transition plan" in heading.inner_text().lower()


def test_back_after_a_redirect_does_not_create_another_flow(page):
    page.goto(f"{URL}/#/argus")
    page.get_by_role("button", name="Start new extraction").wait_for()
    _lands_on_new_step_1(page, "identity")
    after = _flow_count(page)
    page.go_back()
    page.wait_for_timeout(1000)
    assert _flow_count(page) == after


DSN = os.environ.get("ARP_POSTGRES_DSN", "postgresql+psycopg://arp:arp@localhost:5432/arp_test")  # e2e_stack.sh's default


def _theme_run() -> str:
    """A finished theme run with two matches, seeded straight into the stack's store (no model call)."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from arp.schemas.common import JobStatus, RunManifest
    from arp.storage.run_store import RunStore

    store = RunStore(DSN, Settings().runs_dir)
    run_id = f"theme_e2e{uuid4().hex[:8]}"
    store.save_manifest(RunManifest(run_id=run_id, run_type="theme", status=JobStatus.COMPLETED, company_count=2, completed_count=2))
    now = datetime.now(UTC).isoformat()
    matches = [
        {"company_id": cid, "name": name, "ticker": None, "activity_id": "a1", "activity_name": "Green steel", "verdict": "include",
         "exposure_estimate": "significant", "confidence": 0.9, "adjudicator_rationale": "", "citations": [],
         "flagged_for_review": False, "generated_at": now}
        for cid, name in (("hand_a", "Handover Alpha"), ("hand_b", "Handover Beta"))
    ]
    store.append_result(run_id, {"_key": "theme", "company_matches": matches})
    return run_id


def _shows_handed_over(page, names):
    page.wait_for_url(STEP_1)
    for name in names:
        page.get_by_text(name).first.wait_for()
        assert page.get_by_text(name).count() >= 1


def test_thematic_universe_hands_over_to_step_1(page):  # AC-65
    page.goto(f"{URL}/#/theme/{_theme_run()}")
    page.get_by_role("button", name=re.compile(r"Save 2 companies as a universe")).click()
    page.get_by_role("button", name=re.compile(r"Argus")).click()
    _shows_handed_over(page, ["Handover Alpha", "Handover Beta"])


@pytest.mark.parametrize("sub", ["holdings", "monitoring"])  # Data Hub's holdings screen, and a Risk Monitoring tab
def test_portfolio_selection_hands_over_to_step_1(page, sub):  # AC-65
    page.goto(f"{URL}/#/portfolio-monitoring/{sub}")
    send = page.get_by_role("button", name=re.compile(r"^Argus\s*→$"))
    send.wait_for()
    send.click()
    page.wait_for_url(STEP_1)
    fid = STEP_1.search(page.url).group(1)
    rows = _ok(page.request.get(f"{API}/api/argus/flows/{fid}"))["companies"]
    assert len(rows) >= 1  # the seeded demo holdings
    page.get_by_text(rows[0]["name"]).first.wait_for()
    assert page.get_by_text(rows[0]["name"]).count() >= 1


def test_transition_plan_hand_over_preselects_the_template(page):
    page.goto(f"{URL}/#/portfolio-monitoring/holdings")
    send = page.get_by_role("button", name=re.compile(r"Transition plan"))
    send.wait_for()
    send.click()
    page.wait_for_url(STEP_1)
    flow = _ok(page.request.get(f"{API}/api/argus/flows/{STEP_1.search(page.url).group(1)}"))
    assert flow["schema_choice"]["schema_id"] == "transition_plan_indicators" and flow["companies"]


def test_a_failed_hand_over_shows_the_error_and_stays(page):
    page.route(re.compile(r".*/api/argus/flows$"), lambda r: r.fulfill(status=503, body='{"detail": "store down"}')
               if r.request.method == "POST" else r.continue_())
    page.goto(f"{URL}/#/portfolio-monitoring/holdings")
    send = page.get_by_role("button", name=re.compile(r"^Argus\s*→$"))
    send.wait_for()
    send.click()
    alert = page.get_by_role("alert").filter(has_text="store down")
    alert.wait_for()
    assert alert.count() == 1
    assert page.evaluate("location.hash") == "#/portfolio-monitoring/holdings"
    assert send.is_enabled()  # the selection stays and can be sent again


CONTROLS = """r => [...r.querySelectorAll('label, legend, button')].map(e => e.cloneNode(true)).map(e => {
    e.querySelectorAll('select, option, datalist').forEach(x => x.remove());  // saved universes differ between loads
    return e.textContent.trim();
})"""


def test_xbrl_facts_uses_step_1s_company_picker(page):  # AC-67
    labels = ["Upload a list", "Or pick a saved universe", "Add one company"]
    page.goto(f"{URL}/#/argus/new")
    page.wait_for_url(STEP_1)
    page.get_by_role("region", name="Add companies").get_by_text("Add one company").wait_for()
    step_1 = page.get_by_role("region", name="Add companies").evaluate(CONTROLS)
    for label in labels:
        assert label in page.get_by_role("region", name="Add companies").inner_text()
    page.goto(f"{URL}/#/xbrl")
    picker = page.get_by_role("region", name="Add companies")
    picker.wait_for()
    for label in labels:
        assert label in picker.inner_text()
    assert picker.evaluate(CONTROLS) == step_1  # same controls, same labels


# Needs SEC EDGAR over the network: run with ARP_E2E_LIVE=1 (CI's stack has no outside network for this).
@pytest.mark.skipif(not os.environ.get("ARP_E2E_LIVE"), reason="ARP_E2E_LIVE not set -- needs SEC EDGAR")
def test_xbrl_fetch_for_apple_completes_with_facts(page):  # AC-68
    page.set_default_timeout(30_000)
    page.goto(f"{URL}/#/xbrl")
    picker = page.get_by_role("region", name="Add companies")
    picker.get_by_label("Name").fill("Apple Inc.")
    picker.get_by_label("CIK").fill("0000320193")
    picker.get_by_role("button", name="Add").click()
    page.get_by_text("Using 1 company").wait_for()
    page.get_by_role("button", name=re.compile(r"^Start fetch")).click()
    page.wait_for_url(re.compile(r"#/xbrl/[^/]+$"))
    run_id = page.url.rsplit("/", 1)[1]
    import time

    deadline = time.time() + 300
    while (m := _ok(page.request.get(f"{API}/api/xbrl/runs/{run_id}")))["status"] in ("pending", "running") and time.time() < deadline:
        time.sleep(3)
    assert m["status"] == "completed"
    rows = _ok(page.request.get(f"{API}/api/xbrl/runs/{run_id}/results"))["results"]
    assert sum(r["fact_count"] for r in rows) > 0


# AC-69: stored runs of every Argus run type open from Run History with the same counts once the old screens are gone.
OLD_RUNS = [  # run type, results, review items
    ("extraction", 3, 2), ("transition_plan", 2, 1), ("financials", 2, 1), ("tnfd", 1, 1), ("identity", 2, 2), ("discovery", 3, 0),
]


@pytest.fixture
def old_runs():
    from uuid import uuid4

    from arp.schemas.common import JobStatus, RunManifest
    from arp.storage.run_store import RunStore

    store = RunStore(DSN, Settings().runs_dir)
    made = []
    for run_type, results, reviews in OLD_RUNS:
        run_id = f"{run_type}_e2eold{uuid4().hex[:6]}"
        store.save_manifest(RunManifest(run_id=run_id, run_type=run_type, status=JobStatus.COMPLETED, company_count=results,
                                        completed_count=results, review_count=reviews))
        for i in range(results):
            store.append_result(run_id, {"_key": f"c{i}", "company_id": f"c{i}", "name": f"Old {i}", "issuer_key": f"c{i}", "fields": []})
        for i in range(reviews):
            store.append_review_item(run_id, {"item_key": f"c{i}:f:2025", "company_id": f"c{i}", "issuer_key": f"c{i}", "field_id": "f",
                                              "field": {"field_id": "f", "name": "F", "value": 1, "route": "review"}})
        made.append((run_type, run_id, results, reviews))
    return made


def test_stored_runs_open_from_run_history_with_the_same_counts(page, old_runs):  # AC-69
    for run_type, run_id, results, reviews in old_runs:
        page.goto(f"{URL}/#/history/{run_id}")
        row = page.get_by_role("row").filter(has_text=run_id)
        row.wait_for()
        cells = row.inner_text()
        assert f"{results}/{results}" in cells, (run_type, cells)
        if reviews:
            row.get_by_role("button", name="Review").click()
            page.wait_for_function("() => [...document.querySelectorAll('option')].some(o => /^All runs \\(\\d+ items\\)$/.test(o.textContent))")
            option = page.locator("option").filter(has_text=run_id)  # counted once the items have loaded
            assert option.inner_text().endswith(f"({reviews})"), (run_type, option.inner_text())
    assert page.console_errors == []


ALL_SCREENS = [  # the sidebar and the All screens list (App.tsx TABS), minus the company page that needs a ref
    "home", "stewardiq", "argus", "argusWalkthrough", "transitionIntel", "rdLab", "dataHub", "search", "securityMaster", "feeds",
    "issues", "smartSearch", "outputs", "theme", "taxonomy", "emergingThemes", "themes", "backgroundAgents", "transitionBarrier",
    "portfolio-monitoring", "review", "history", "plans", "stewardship", "engagement", "voting", "reporting", "strategyReplication",
    "signals", "valueChain", "decision", "index", "xbrl", "rfp", "library", "arcade",
]


def test_no_screen_shows_the_old_pipeline_diagrams(page):  # AC-66
    for screen in ALL_SCREENS:
        page.goto(f"{URL}/#/{screen}")
        page.locator("main#main").wait_for()
        page.wait_for_load_state("networkidle")
        assert page.locator(".pipeline-rf, .stage-rf").count() == 0, screen


def test_company_upload_only_on_step_1_and_xbrl_document_upload_only_on_step_2(page):  # AC-66 (Argus pages, owner 2026-11-10)
    api = page.request
    fid = _ok(api.post(API + "/api/argus/flows"))["flow_id"]
    _ok(api.post(f"{API}/api/argus/flows/{fid}/companies", data={"company": {"name": "Upload Check Co"}}))
    _ok(api.patch(f"{API}/api/argus/flows/{fid}", data={"source": "upload", "step": 3}))
    company_upload, file_inputs = {}, {}
    for route in (f"argus/{fid}/1", f"argus/{fid}/2", f"argus/{fid}/3", "argus", "argusWalkthrough", "xbrl", "review"):
        page.goto(f"{URL}/#/{route}")
        page.locator("main#main h1").first.wait_for()
        page.wait_for_load_state("networkidle")
        company_upload[route] = page.get_by_role("region", name="Add companies").count()
        file_inputs[route] = page.locator("main input[type=file]").count()
    assert [r for r, n in company_upload.items() if n] == [f"argus/{fid}/1", "xbrl"]
    assert [r for r, n in file_inputs.items() if n] == [f"argus/{fid}/1", f"argus/{fid}/2", "xbrl"]  # step 2's are document uploads
