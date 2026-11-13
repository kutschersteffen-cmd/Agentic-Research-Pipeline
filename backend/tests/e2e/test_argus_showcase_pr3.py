"""showcase-argus-fixes, PR 3 in the browser: steps 4 and 5, the company link in the Data Library, XBRL Add one company.

Runs are seeded straight into the stack's store (no model call), as in test_argus_steps45.py."""

import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from arp.argus.flows import FlowStore
from arp.config import Settings
from arp.schemas.common import CompanyRef, JobStatus, RunManifest
from arp.storage.run_store import RunStore

URL = os.environ.get("ARP_E2E_URL")
API = os.environ.get("ARP_E2E_API_URL", "http://127.0.0.1:8000")
DSN = os.environ.get("ARP_POSTGRES_DSN", "postgresql+psycopg://arp:arp@localhost:5432/arp_test")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

TAG = uuid4().hex[:6]
CODES = ("unreleased_version", "check_failed", "first_audit_pending", "below_auto_accept_min")


def _field(fid, value, route, *, period="2025-12-31", reasons=()):
    return {"field_id": fid, "field_name": fid.title(), "value": value, "citations": [], "confidence": 0.9, "grounded": True,
            "conflicting_sources": False, "value_state": "found", "route": route, "route_reasons": list(reasons), "period_end": period}


def _run(store, companies, *, status=JobStatus.COMPLETED, done=None, created=None):
    run_id = f"extraction_e2e3{uuid4().hex[:8]}"
    store.save_manifest(RunManifest(
        run_id=run_id, run_type="extraction", status=status, company_count=len(companies),
        completed_count=len(companies) if done is None else done, created_at=(created or datetime.now(UTC)).isoformat(),
        params={"schema_name": "Showcase", "schema_version": "sch_s:v1"}))
    store.save_companies(run_id, [CompanyRef(company_id=k, name=v) for k, v in companies.items()])
    (store.run_dir(run_id) / "start_request.json").write_text(json.dumps(
        {"profile": "custom", "companies": [{"company_id": k, "name": v} for k, v in companies.items()]}))
    return run_id


def _result(store, run_id, cid, name, fields, *, items=()):
    issuer = f"k{cid}"
    store.append_result(run_id, {"_key": cid, "company_id": cid, "name": name, "issuer_key": issuer, "schema_id": "sch_s",
                                 "run_id": run_id, "overall_confidence": 0.9, "needs_review": bool(items), "fields": fields})
    for f in fields:
        if f["field_id"] in items:
            store.append_review_item(run_id, {"item_key": f"{issuer}:{f['field_id']}:{f['period_end']}", "company_id": cid,
                                              "issuer_key": issuer, "field_id": f["field_id"], "period_end": f["period_end"], "field": f})


def _flow(run_id, step):
    from arp.api.auth import Principal

    flows = FlowStore(Settings().runs_dir / "_flows")
    flow = flows.create(Principal(user_id="dev", name="dev", role="approver"))
    flows.update(flow.flow_id, lambda f: (setattr(f, "run_id", run_id), setattr(f, "step", step)))
    return flow.flow_id


@pytest.fixture
def store():
    return RunStore(DSN, Settings().runs_dir)


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


def _rows(page, table):
    t = page.get_by_role("table", name=table)
    t.locator("tbody tr").first.wait_for()
    return t.locator("tbody tr")


# --- Step 4 ---------------------------------------------------------------------------------------------------------

def test_the_step_bar_links_results_once_the_run_ends(page, store):  # AC-107
    run_id = _run(store, {f"a{TAG}": "Alder"}, status=JobStatus.RUNNING, done=0)
    fid = _flow(run_id, 4)
    page.goto(f"{URL}/#/argus/{fid}/4")
    steps = page.get_by_role("navigation", name="Steps")
    steps.get_by_text("5 Results").wait_for()
    assert steps.get_by_role("link", name="5 Results").count() == 0
    m = store.load_manifest(run_id)
    store.save_manifest(m.model_copy(update={"status": JobStatus.COMPLETED, "completed_count": 1}))
    steps.get_by_role("link", name="5 Results").wait_for()  # no reload


def test_stop_reads_stopping_and_says_what_happens(page, store):  # AC-108, AC-109
    run_id = _run(store, {f"a{TAG}": "Alder", f"b{TAG}": "Birch"}, status=JobStatus.RUNNING, done=0)
    page.goto(f"{URL}/#/argus/{_flow(run_id, 4)}/4")
    page.get_by_role("button", name="Stop").click()
    stopping = page.get_by_role("button", name="Stopping…")
    stopping.wait_for()
    assert stopping.is_disabled()
    page.get_by_text("Stopping: companies already running will finish.", exact=True).wait_for()
    assert page.console_errors == []


def test_a_company_dropped_for_conflicting_identifiers_reads_failed_without_retry(page, store):  # AC-110, AC-111
    a, b, c = f"apple{TAG}", f"msft{TAG}", f"mixed{TAG}"
    run_id = _run(store, {a: "Apple", b: "Microsoft", c: "Mixed"}, done=2,
                  created=datetime.now(UTC) - timedelta(minutes=5))
    for cid, name in ((a, "Apple"), (b, "Microsoft")):
        _result(store, run_id, cid, name, [_field("capex", 1, "auto_accept")])
    store.append_error(run_id, {"company_id": c, "kind": "identity_conflict", "error": "Identifiers match more than one company"})
    page.goto(f"{URL}/#/argus/{_flow(run_id, 4)}/4")
    row = _rows(page, "Companies in this run").filter(has_text="Mixed")
    assert "Failed" in row.inner_text()
    assert "Identifiers match more than one company. Correct them in a new extraction." in row.inner_text()
    assert row.get_by_role("button", name="Retry").count() == 0
    line = page.get_by_role("status").filter(has_text="Started")
    assert re.fullmatch(r"Started \d\d:\d\d · 3 of 3 done · \$0\.00 so far", line.inner_text())


def test_a_done_row_has_a_full_bar(page, store):  # AC-151 (AC-112's stages need a live run: see the PR)
    run_id = _run(store, {f"a{TAG}": "Alder"})
    _result(store, run_id, f"a{TAG}", "Alder", [_field("capex", 1, "auto_accept")])
    page.goto(f"{URL}/#/argus/{_flow(run_id, 4)}/4")
    bar = _rows(page, "Companies in this run").first.get_by_role("progressbar")
    page.wait_for_timeout(600)  # the fill eases in
    full, fill = bar.bounding_box()["width"], bar.locator(".progress-bar-fill").bounding_box()["width"]
    assert abs(full - fill) < 1, (full, fill)


# --- Step 5 ---------------------------------------------------------------------------------------------------------

def test_values_show_their_period_and_how_they_were_found(page, store):  # AC-113, AC-121
    a = f"apple{TAG}"
    run_id = _run(store, {a: "Apple"})
    _result(store, run_id, a, "Apple", [_field("revenue", 10, "auto_accept", period="2025-06-30"),
                                        _field("revenue", 12, "auto_accept", period="2026-06-30")])
    page.goto(f"{URL}/#/argus/{_flow(run_id, 5)}/5")
    rows = _rows(page, "Extracted values")
    heads = page.get_by_role("table", name="Extracted values").locator("thead th").all_text_contents()
    assert heads[heads.index("Field") + 1] == "Period"
    assert [r.locator("td[data-label='Period']").inner_text() for r in rows.all()] == ["2026-06-30", "2025-06-30"]
    link = rows.first.locator("a", has_text="How was this found?")
    assert link.get_attribute("href") == f"#/argusWalkthrough/{run_id}/{a}/revenue/2026-06-30"
    link.click()
    page.wait_for_url(re.compile(rf"#/argusWalkthrough/{run_id}/{a}/revenue/2026-06-30$"))


def test_the_review_detail_shows_no_reason_codes(page, store):  # AC-117
    a = f"apple{TAG}"
    run_id = _run(store, {a: "Apple"})
    _result(store, run_id, a, "Apple", [_field("capex", 12, "review", reasons=CODES)], items=("capex",))
    page.goto(f"{URL}/#/argus/{_flow(run_id, 5)}/5")
    _rows(page, "Extracted values").first.get_by_role("button", name="Review").click()
    detail = page.locator(".decision-view")
    detail.wait_for()
    text = detail.inner_text()
    assert not [c for c in CODES if c in text], text
    assert ("Routed for review: The schema is a draft, so every value is reviewed. A check on this value failed. "
            "The first values of a new schema version are always reviewed. "
            "Confidence is below the level for automatic acceptance.") in text  # AC-114 as the owner chose on #446


@pytest.fixture
def kept(store, page):
    """Apple in a new run; Microsoft set to "Skip, keep earlier results" with 4 values from the run of 2026-11-10."""
    a, m = f"apple{TAG}", f"msft{TAG}"
    old = _run(store, {m: "Microsoft"}, created=datetime(2026, 11, 10, 9, tzinfo=UTC))
    _result(store, old, m, "Microsoft", [_field(f"f{i}", i, "review" if i == 0 else "auto_accept") for i in range(4)], items=("f0",))
    new = _run(store, {a: "Apple"})
    _result(store, new, a, "Apple", [_field("capex", 7, "auto_accept")])
    fid = _flow(new, 5)

    def with_kept(route):  # the repeat rule needs kept files and schema versions; the flow is given its outcome
        flow = route.fetch().json()
        flow["companies"] = [{"company_id": a, "name": "Apple"}, {"company_id": m, "name": "Microsoft"}]
        flow["repeat"] = {m: "skip"}
        flow["repeat_rows"] = [{"company_id": m, "kind": "same", "added": 0, "run_id": old, "date": "2026-11-10", "approved": 3, "waiting": 1}]
        route.fulfill(json=flow)

    page.route(f"**/api/argus/flows/{fid}", with_kept)
    return fid, old, m


def test_a_kept_companys_values_are_listed_and_marked(page, kept):  # AC-118, AC-120
    fid, _, _ = kept
    page.goto(f"{URL}/#/argus/{fid}/5")
    rows = _rows(page, "Extracted values")
    rows.nth(4).wait_for()
    micro = [r for r in rows.all() if r.locator("td[data-label='Company']").inner_text().startswith("Microsoft")]
    assert len(micro) == 4 and rows.filter(has_text="Apple").count() == 1
    for r in micro:
        assert "kept from the extraction of 2026-11-10" in r.locator("td[data-label='Company']").inner_text()
    note = "This run covers 1 of 2 companies. Not in it: Microsoft (kept from the extraction of 2026-11-10, open)."
    assert note in page.get_by_role("note").inner_text()
    assert page.console_errors == []


def test_a_kept_value_is_reviewed_and_walked_through_in_its_own_run(page, kept):  # AC-119, AC-150
    fid, old, m = kept
    page.goto(f"{URL}/#/argus/{fid}/5")
    row = _rows(page, "Extracted values").filter(has_text="Microsoft").filter(has=page.get_by_role("button", name="Approve")).first
    assert row.locator("a", has_text="How was this found?").get_attribute("href").startswith(f"#/argusWalkthrough/{old}/{m}/")
    row.get_by_role("button", name="Approve").click()
    with page.expect_response(lambda r: f"/api/review/runs/{old}/items/" in r.url and r.request.method == "POST") as info:
        row.get_by_role("button", name="Submit").click()
    assert info.value.ok, info.value.text()
    # recorded on the earlier run (a sampled second review may still be due, so it need not be final)
    states = page.request.get(f"{API}/api/extraction/runs/{old}/review-decisions").json()["states"]
    assert states.get(f"k{m}:f0:2025-12-31", {}).get("state") in ("first_done", "final"), states


# --- Elsewhere ------------------------------------------------------------------------------------------------------

def test_the_company_link_opens_the_central_record(page, store):  # AC-127
    api = page.request
    fid = api.post(f"{API}/api/argus/flows").json()["flow_id"]
    name, isin = f"Apple {TAG}", f"XS{int(TAG, 16) % 10**10:010d}"  # its own company: the register is shared by every test
    r = api.post(f"{API}/api/argus/flows/{fid}/companies", data={"company": {"name": name, "isin": isin}})
    assert r.ok, r.text()
    central = r.json()["companies"][0]["entity_id"]
    assert central
    cid = f"apple-list-{TAG}"  # a key that names no register record
    run_id = _run(store, {cid: name})
    (store.run_dir(run_id) / "start_request.json").write_text(json.dumps(
        {"profile": "custom", "companies": [{"company_id": cid, "name": name, "entity_id": central}]}))
    _result(store, run_id, cid, name, [_field("capex", 1, "auto_accept")])
    page.goto(f"{URL}/#/library")
    page.locator(f"select:has(option[value='{run_id}'])").select_option(run_id)
    link = page.get_by_role("link", name=name, exact=True)
    link.wait_for()
    page.wait_for_function(f"() => document.querySelector('a[href=\"#/companies/{central}\"]')")
    link.click()
    page.get_by_role("heading", name=name).first.wait_for()
    page.get_by_text(isin).first.wait_for()


def _xbrl(page):
    page.goto(f"{URL}/#/xbrl")
    picker = page.get_by_role("region", name="Add companies")
    picker.wait_for()
    return picker


def _saved(page, n):
    """A saved universe of n companies; its path."""
    companies = [{"company_id": f"s{TAG}{i}", "name": f"Saved {i}", "cik": str(320193 + i)} for i in range(n)]
    r = page.request.post(f"{API}/api/universe/from-companies", data={"companies": companies, "name": f"saved{n}_{TAG}"})
    assert r.ok, r.text()
    return r.json()["path"]


def _pick(page, picker, path):
    page.wait_for_function(f"() => document.querySelector('option[value=\"{path}\"]')")
    picker.get_by_label("Or pick a saved universe").select_option(value=path)


def _add_one(page, picker, name="Microsoft", cik="789019"):
    form = picker.locator("fieldset").filter(has_text="Add one company")
    form.get_by_label("Name").fill(name)
    form.get_by_label("CIK").fill(cik)
    form.get_by_role("button", name="Add").click()


def _using(page, n):
    page.get_by_text(f"Using {n} {'company' if n == 1 else 'companies'}.", exact=True).wait_for()


def test_xbrl_add_one_extends_the_picked_list(page):  # AC-129, AC-130, AC-132, AC-133, AC-152
    one = _saved(page, 1)
    picker = _xbrl(page)
    _pick(page, picker, one)
    _using(page, 1)
    _add_one(page, picker)
    _using(page, 2)  # AC-129
    with page.expect_request(lambda r: r.url.endswith("/api/xbrl/runs") and r.method == "POST") as req:
        page.get_by_role("button", name=re.compile(r"^Start fetch for 2 companies")).click()  # AC-130
    assert len(json.loads(Path(req.value.post_data_json["universe_path"]).read_text())) == 2
    _add_one(page, picker)
    _using(page, 2)  # AC-132
    picker.get_by_label("Upload a list").set_input_files(
        files=[{"name": f"three{TAG}.csv", "mimeType": "text/csv", "buffer": b"company_id,name\nx1,X1\nx2,X2\nx3,X3\n"}])
    _using(page, 3)  # AC-133
    page.reload()  # AC-152: opened again, the first saved universe still has its one company
    picker = page.get_by_role("region", name="Add companies")
    _pick(page, picker, one)
    _using(page, 1)
    assert len(json.loads(Path(one).read_text())) == 1


def test_xbrl_picks_a_saved_universe_and_adds_one_to_nothing(page):  # AC-131, AC-153
    five = _saved(page, 5)
    picker = _xbrl(page)
    _add_one(page, picker, name=f"Solo {TAG}", cik="1018724")
    _using(page, 1)  # AC-131
    _pick(page, picker, five)
    _using(page, 5)  # AC-153


# --- Review round 1 (code and UI review on #446) --------------------------------------------------------------------

def _active(page):
    return page.evaluate("() => [document.activeElement.tagName, document.activeElement.textContent.trim()]")


@pytest.mark.parametrize("fails", [False, True])
def test_stop_keeps_the_keyboard_focus(page, store, fails):  # UI review 1: not on <body>, whether Stop works or fails
    run_id = _run(store, {f"a{TAG}": "Alder"}, status=JobStatus.RUNNING, done=0)
    if fails:
        page.route("**/api/runs/*/cancel", lambda r: r.fulfill(status=500, json={"detail": "Cancel failed"}))
    page.goto(f"{URL}/#/argus/{_flow(run_id, 4)}/4")
    page.get_by_role("button", name="Stop").focus()
    page.keyboard.press("Enter")
    if fails:
        page.get_by_role("alert").filter(has_text="Cancel failed").wait_for()
        assert _active(page) == ["BUTTON", "Stop"]
    else:
        page.get_by_role("button", name="Stopping…").wait_for()
        assert _active(page) == ["BUTTON", "Stopping…"]


@pytest.fixture
def failed(store):
    """A finished run whose Birch failed with an error Retry accepts."""
    a, b = f"alder{TAG}", f"birch{TAG}"
    run_id = _run(store, {a: "Alder", b: "Birch"}, status=JobStatus.PARTIALLY_COMPLETED, done=1)
    _result(store, run_id, a, "Alder", [_field("capex", 1, "auto_accept")])
    store.append_error(run_id, {"key": b, "error": "The model call timed out"})
    return _flow(run_id, 4)


def test_retry_names_its_row_and_keeps_the_focus_when_it_fails(page, failed):  # UI review 2, 3
    page.route("**/companies/*/retry", lambda r: r.fulfill(status=500, json={"detail": "Retry failed"}))
    page.goto(f"{URL}/#/argus/{failed}/4")
    retry = page.get_by_role("button", name="Retry Birch")
    retry.focus()
    page.keyboard.press("Enter")
    page.get_by_role("alert").filter(has_text="Retry failed").wait_for()
    assert page.evaluate("() => document.activeElement.getAttribute('aria-label')") == "Retry Birch"


def test_a_retry_that_works_moves_the_focus_to_the_status_line(page, failed):  # UI review 2
    page.goto(f"{URL}/#/argus/{failed}/4")
    page.get_by_role("button", name="Retry Birch").focus()
    page.keyboard.press("Enter")
    page.wait_for_function("() => document.activeElement.classList.contains('argus-progress-line')")


def test_how_was_this_found_names_its_row_and_fits_a_phone(page, store):  # UI review 4, 5
    a = f"apple{TAG}"
    run_id = _run(store, {a: "Apple"})
    _result(store, run_id, a, "Apple", [_field("revenue", 12, "review", period="2026-06-30")], items=("revenue",))
    fid = _flow(run_id, 5)
    page.goto(f"{URL}/#/argus/{fid}/5")
    page.get_by_role("link", name="How was Revenue 2026-06-30 for Apple found?").wait_for()
    page.set_viewport_size({"width": 390, "height": 844})
    link = _rows(page, "Extracted values").first.get_by_role("link", name="How was Revenue 2026-06-30 for Apple found?")
    box, controls = link.bounding_box(), page.locator(".review-controls").first.bounding_box()
    assert box["x"] + box["width"] <= 390 - 8, box  # not clipped at the card's edge
    assert box["height"] < 30, box  # one line, not a word per line
    assert box["y"] >= controls["y"] + controls["height"], (box, controls)  # on its own line under the controls


def test_the_unit_note_reads_as_a_sentence_in_the_data_library(page, store):  # code review 1 (AC-116 on screen)
    a = f"steel{TAG}"
    run_id = _run(store, {a: "Steelco"})
    f = {**_field("emissions", 12.5, "review"),
         "verifier_notes": "No grounded citation supports this value. cannot convert 'short tons' to 'tCO2e' (unknown_unit)"}
    _result(store, run_id, a, "Steelco", [f])
    page.goto(f"{URL}/#/library")
    page.locator(f"select:has(option[value='{run_id}'])").select_option(run_id)
    page.get_by_role("link", name="Steelco", exact=True).wait_for()
    page.locator("tr.clickable-row").filter(has_text="Steelco").locator("td").nth(1).click()
    page.get_by_text('The unit "short tons" could not be converted to tCO2e.', exact=False).wait_for()
    assert "cannot convert" not in page.locator(".field-detail").first.inner_text()


def test_an_earlier_run_is_read_once_for_all_its_kept_companies(page, store):  # code review 2
    a, m, s = f"apple{TAG}", f"msft{TAG}", f"sap{TAG}"
    old = _run(store, {m: "Microsoft", s: "SAP"}, created=datetime(2026, 11, 10, 9, tzinfo=UTC))
    for cid, name in ((m, "Microsoft"), (s, "SAP")):
        _result(store, old, cid, name, [_field("capex", 1, "auto_accept")])
    new = _run(store, {a: "Apple"})
    _result(store, new, a, "Apple", [_field("capex", 7, "auto_accept")])
    fid = _flow(new, 5)

    def with_kept(route):
        flow = route.fetch().json()
        flow["companies"] = [{"company_id": c, "name": n} for c, n in ((a, "Apple"), (m, "Microsoft"), (s, "SAP"))]
        flow["repeat"] = {m: "skip", s: "skip"}
        flow["repeat_rows"] = [{"company_id": c, "kind": "same", "added": 0, "run_id": old, "date": "2026-11-10", "approved": 1, "waiting": 0}
                               for c in (m, s)]
        route.fulfill(json=flow)

    page.route(f"**/api/argus/flows/{fid}", with_kept)
    reads = []
    page.on("request", lambda r: f"/api/extraction/runs/{old}/results" in r.url and reads.append(r.url))
    page.goto(f"{URL}/#/argus/{fid}/5")
    rows = _rows(page, "Extracted values")
    rows.nth(2).wait_for()
    assert rows.filter(has_text="kept from the extraction of 2026-11-10").count() == 2
    assert len(reads) == 1, reads
