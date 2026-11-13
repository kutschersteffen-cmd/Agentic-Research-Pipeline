"""Showcase fixes, R&D Lab screens (spec showcase-themes-fixes, PR 2), with the API stubbed by Playwright routing."""

import json

import pytest

from arp.config import Settings
from tests.e2e.test_showcase_themes_screens import URL, manifest, pytestmark  # noqa: F401 - pytestmark marks this module


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.set_default_timeout(10_000)
        yield page
        browser.close()

THEME_RESULTS = "**/api/themes/runs/{}/results*"


def _card(page, **kw):
    page.route("**/api/runs/run_t", lambda r: r.fulfill(json=manifest(**kw)))
    page.route(THEME_RESULTS.format("run_t"), lambda r: r.fulfill(json={"results": []}))
    page.goto(f"{URL}/#/theme/run_t")
    page.locator(".run-progress").wait_for()


def test_emerging_scan_counts_mentions(page):  # AC-50
    _card(page, run_type="emerging_themes", company_count=618, completed_count=618, input_tokens=5)
    page.get_by_text("618/618 mentions").wait_for()
    assert page.get_by_role("progressbar").get_attribute("aria-valuetext") == "618 of 618 mentions, 0 failed"


def test_theme_run_counts_companies(page):  # AC-98
    _card(page, completed_count=2, input_tokens=5)
    page.get_by_text("2/5 companies").wait_for()


def test_no_model_calls_instead_of_zero_cost(page):  # AC-81
    _card(page)
    page.get_by_text("No new model calls (answers reused or nothing to read)").wait_for()
    assert page.get_by_text("$0.00").count() == 0


CANDIDATE = {"theme_id": "e1", "theme_name": "Heat pumps", "description": "d", "first_detected_date": "2026-11-11",
             "signal_velocity": 1.0, "breadth": 0.1, "persistence": 0, "novelty": 1.0, "corroborating_sources": [],
             "candidate_sectors_companies": [], "rationale": "r", "economic_rationale": "e", "confidence_score": 1.0,
             "action_score": 0.0, "xbrl_corroboration": [], "materiality": 0.0, "contradiction": 0.0,
             "contradiction_evidence": [], "company_exposure": [], "context_brief": None, "status": "candidate",
             "cluster_id": "k", "run_id": "et1", "created_at": "2026-11-11T09:00:00Z"}


class Counter:
    def __init__(self, page, pattern, answer):
        self.count, self.answer = 0, answer
        page.route(pattern, self.handle)

    def handle(self, route):
        self.count += 1
        route.fulfill(json=self.answer(self.count))


def _emerging(page, statuses, candidates):
    runs = Counter(page, "**/api/runs?run_type=emerging_themes", lambda n: {"runs": [
        manifest(run_id="et1", run_type="emerging_themes", status=statuses(n))]})
    page.route("**/api/emerging-themes/runs/et1/candidates",
               lambda r: r.fulfill(json={"candidates": candidates(runs.count)}))
    page.goto(f"{URL}/#/emergingThemes")
    page.get_by_role("button", name="View candidates").click()
    return runs


def test_scanning_then_candidates_appear(page):  # AC-53, AC-54
    _emerging(page, lambda n: "running" if n < 3 else "completed", lambda n: [CANDIDATE] if n >= 3 else [])
    page.get_by_text("Scanning… candidates appear when the scan finishes.").wait_for()
    assert page.get_by_text("No candidates for this run").count() == 0
    page.get_by_role("cell", name="Heat pumps").wait_for(timeout=10_000)
    assert page.locator(".status-pill").first.text_content() == "completed"


def test_scan_polling_survives_a_failed_reload(page):  # AC-54 (code review: one failed list request must not stop polling)
    calls = []

    def runs(route):
        calls.append(1)
        if len(calls) == 2:
            return route.fulfill(status=500, json={"detail": "boom"})
        status = "running" if len(calls) < 4 else "completed"
        route.fulfill(json={"runs": [manifest(run_id="et1", run_type="emerging_themes", status=status)]})

    page.route("**/api/runs?run_type=emerging_themes", runs)
    page.route("**/api/emerging-themes/runs/et1/candidates",
               lambda r: r.fulfill(json={"candidates": [CANDIDATE] if len(calls) >= 4 else []}))
    page.goto(f"{URL}/#/emergingThemes")
    page.get_by_role("button", name="View candidates").click()
    page.get_by_role("cell", name="Heat pumps").wait_for(timeout=15_000)


def test_novelty_and_no_companies(page):  # AC-55, AC-56
    _emerging(page, lambda n: "completed", lambda n: [CANDIDATE])
    page.get_by_role("columnheader", name="Novelty").wait_for()
    page.get_by_text("How different this cluster is from themes in earlier scans. 100% on a first scan.").wait_for()
    assert page.get_by_role("cell", name="None in your universe").count() == 1
    assert "Confidence" not in page.locator("body").inner_text()


def test_schedule_refuses_zero_and_says_saved(page):  # AC-58, AC-59
    schedule = {"enabled": False, "interval_hours": 168, "universe_path": None, "last_run_id": None, "next_run_at": None,
                "calendar_dates": [], "calendar_rule": None, "last_calendar_fire": None}
    puts = []

    def handle(route):
        if route.request.method == "PUT":
            puts.append(route.request.post_data_json)
            return route.fulfill(json=route.request.post_data_json)
        route.fulfill(json=schedule)

    page.route("**/api/emerging-themes/schedule", handle)
    page.goto(f"{URL}/#/emergingThemes")
    interval = page.get_by_label("Interval (hours)")
    interval.fill("0")
    page.get_by_role("button", name="Save schedule").click()
    page.get_by_text("Enter an interval of at least 1 hour.").wait_for()
    assert puts == []
    interval.fill("24")
    page.get_by_role("button", name="Save schedule").click()
    page.get_by_text("Schedule saved.").wait_for()
    assert puts[0]["interval_hours"] == 24


def test_dossier_step_4_links_to_the_review(page):  # AC-61
    page.route("**/api/dossiers/d1", lambda r: r.fulfill(json={
        "dossier_id": "d1", "name": "Grid", "origin": "topic", "status": "active", "taxonomy_id": "t", "context_brief": None,
        "steps": [{"number": 4, "title": "Find companies", "state": "waiting", "detail": "1 to review", "href": "#/review/theme/r1"}]}))
    page.goto(f"{URL}/#/themes/d1")
    link = page.get_by_role("link", name="Review the open items")
    assert link.get_attribute("href") == "#/review/theme/r1"


def test_unshelve_keeps_keyboard_focus(page):  # AC-89 (UI review: focus must not drop to <body>)
    dossier = {"dossier_id": "d1", "name": "Grid", "origin": "topic", "taxonomy_id": None, "context_brief": None, "steps": [],
               "status": "shelved", "shelved_by": "ana", "shelved_at": "2026-11-11T09:00:00Z", "shelve_reason": "parked"}
    active = dict(dossier, status="active", shelved_by=None, shelved_at=None, shelve_reason=None)
    page.route("**/api/dossiers/d1", lambda r: r.fulfill(json=active if r.request.method == "PATCH" else dossier))
    page.goto(f"{URL}/#/themes/d1")
    page.get_by_role("button", name="Un-shelve").focus()
    page.keyboard.press("Enter")
    page.get_by_text("Dossier is active again.").wait_for()
    assert page.evaluate("document.activeElement.textContent") == "Dossier is active again."
    assert page.get_by_role("status").filter(has=page.get_by_role("button")).count() == 0


def _plan(status, calls):
    return {"id": "p1", "brief": "b", "script": "s", "status": status, "approved_by": "a", "approved_at": None, "error": None,
            "version": 1, "previous_scripts": [], "calls": calls,
            "dry_run": [{"seq": c["seq"], "kind": c["kind"], "params": {}, "depends_on": None} for c in calls]}


def test_plan_step_waiting_links_to_review(page):  # AC-62, AC-64, AC-128
    calls = [{"seq": 1, "kind": "extraction", "params": {}, "status": "awaiting_review", "run_id": "r_1", "result_ref": None},
             {"seq": 2, "kind": "report_render", "params": {}, "status": "awaiting_review", "run_id": None, "result_ref": "report:7"},
             {"seq": 3, "kind": "xbrl_facts", "params": {}, "status": "awaiting_review", "run_id": "x", "result_ref": None}]
    plan = _plan("awaiting_review", calls)
    page.route("**/api/plans", lambda r: r.fulfill(json=[plan]))
    page.route("**/api/plans/p1", lambda r: r.fulfill(json=plan))
    page.goto(f"{URL}/#/plans/p1")
    links = page.get_by_role("link", name="Review", exact=True)
    links.first.wait_for()
    assert [links.nth(i).get_attribute("href") for i in range(links.count())] == ["#/review/extraction/r_1", "#/reporting"]


def test_plans_list_follows_the_open_plan(page):  # AC-90
    calls = [{"seq": 1, "kind": "extraction", "params": {}, "status": "running", "run_id": "r", "result_ref": None}]
    detail = Counter(page, "**/api/plans/p1", lambda n: _plan("running" if n < 2 else "failed", calls))
    page.route("**/api/plans", lambda r: r.fulfill(json=[_plan("running" if detail.count < 2 else "failed", calls)]))
    page.goto(f"{URL}/#/plans/p1")
    row = page.locator("li").filter(has=page.get_by_role("button", name="b", exact=True))
    row.get_by_text("running").wait_for()
    row.get_by_text("failed").wait_for(timeout=8_000)


def _catalogue(page, available=True):
    def handle(route):
        body = route.fetch().json()
        body["constraint_solver"]["available"] = available
        route.fulfill(json=body)

    page.route("**/api/index/catalogue", handle)


def test_index_banner_and_missing_solver(page):  # AC-65, AC-69
    _catalogue(page, available=False)
    page.goto(f"{URL}/#/index")
    page.get_by_text("The optimiser is not installed on this server. A calibration that asks for it").wait_for()
    banner = "Demo data: reviews on this page run on a built-in synthetic universe of 60 companies. The results describe nothing real."
    for tab in ("Compose", "Result"):
        page.get_by_role("tab", name=tab).click()
        page.get_by_text(banner).wait_for()
    page.get_by_role("tab", name="Compose").click()
    assert "pip install" not in page.locator("body").inner_text()


def _review(page, answer):
    _catalogue(page)
    page.route("**/api/index/run", answer)
    page.goto(f"{URL}/#/index")
    page.get_by_role("button", name="Preview").click()


def test_cvxpy_fallback_in_plain_words(page):  # AC-66
    def answer(route):  # the real review, with the server's fallback exception added
        body = route.fetch().json()
        body["exceptions"] = ["solver.method='least_squares' but cvxpy is not installed; fell back to the deterministic "
                              'waterfall (pip install -e ".[optimize]")']
        route.fulfill(json=body)

    _review(page, answer)
    page.get_by_text('The optimiser is not installed on this server, so this review used step-by-step capping instead of '
                     '"Least-squares projection". Ask your administrator.').wait_for()


def test_screen_error_named_like_the_card(page):  # AC-70, AC-71
    _review(page, lambda r: r.fulfill(status=422, json={"detail": [{
        "loc": ["body", "spec", "screens", 0, "metric_threshold"],
        "msg": "Value error, metric_threshold needs at least one of min_value / max_value"}]}))
    page.get_by_text("Screen 1 (Metric threshold): needs at least one of min_value / max_value", exact=True).wait_for()


def test_metric_tilt_card_title(page):  # AC-124
    _catalogue(page)
    page.goto(f"{URL}/#/index")
    page.get_by_role("button", name="+ Metric tilt").click()
    page.locator(".activity-editor strong", has_text="Metric tilt").wait_for()


EXPERIMENT = {"method": "price_momentum", "category": "c", "universe": "u", "window_start": "2016-01-31",
              "window_end": "2019-04-30", "n_trials": 1, "model": None, "cutoff": None, "cutoff_status": "not_applicable",
              "decision": "none"}


def test_signals_columns_rerun_and_samples(page):  # AC-72, AC-73, AC-74, AC-123
    rows = [dict(EXPERIMENT, experiment_id="aaaaaaaa1111", created_at="2026-11-11T09:05:00Z"),
            dict(EXPERIMENT, experiment_id="bbbbbbbb2222", created_at="2026-11-11T09:07:00Z")]
    detail = {**rows[0], "recipe": {"method": "price_momentum"}, "decided_by": None, "evidence": {"windows": [
        {"window": "out_of_window", "periods": 10, "ic": {"mean": 0.0423456, "t_nw": 2.34567, "n": 10}},
        {"window": "in_window", "periods": 10, "ic": {"mean": None, "t_nw": None, "n": 0}}]}}
    page.route("**/api/signals/experiments", lambda r: r.fulfill(json=rows))
    page.route("**/api/signals/experiments/*", lambda r: r.fulfill(json=detail))
    page.route("**/api/signals/methods", lambda r: r.fulfill(json=[]))
    page.route("**/api/signals/runs", lambda r: r.fulfill(json=detail))
    page.goto(f"{URL}/#/signals")
    assert page.get_by_role("link", name="Sample recipe (JSON)").get_attribute("href") == "samples/signals-recipe.json"
    assert page.get_by_role("link", name="Sample prices (CSV)").get_attribute("href") == "samples/signals-prices.csv"
    page.get_by_role("columnheader", name="Created").wait_for()
    page.get_by_role("columnheader", name="ID", exact=True).wait_for()
    texts = page.locator("tbody tr").all_inner_texts()
    assert "aaaaaaaa" in texts[0] and "bbbbbbbb" in texts[1]
    assert "2026-11-11 09:05" in texts[0] and "2026-11-11 09:07" in texts[1]  # the CI browser runs in UTC
    page.locator("input[type=file][accept='.json,application/json']").set_input_files(
        files=[{"name": "r.json", "mimeType": "application/json", "buffer": json.dumps({"method": "x"}).encode()}])
    page.locator("input[type=file][accept='.csv']").first.set_input_files(
        files=[{"name": "p.csv", "mimeType": "text/csv", "buffer": b"date,A\n"}])
    page.get_by_role("button", name="Submit").click()
    page.get_by_text("This recipe was already run on this data. Showing the existing result (aaaaaaaa1111).").wait_for()
    page.get_by_role("cell", name="0.042", exact=True).wait_for()
    assert page.get_by_role("cell", name="2.346", exact=True).count() == 1
    assert page.get_by_role("cell", name="—", exact=True).count() >= 2


TAXONOMY = {"taxonomy_id": "tax1", "name": "Grid", "version": 1, "status": "ratified", "derivation_method": "manual",
            "theme": {"name": "Grid", "description": "d", "activities": []}, "created_at": "2026-11-11T09:00:00Z",
            "source_notes": "", "ratified_by": "a", "ratified_at": "2026-11-11T09:00:00Z"}


def _outputs(route):
    kind = route.request.url.split("kind=")[-1]
    item = {"kind": kind, "version": 1, "as_of": None, "status": "ratified", "by": None, "used_by": []}
    if kind == "taxonomy":
        return route.fulfill(json={"outputs": [dict(item, id="tax1", name="Grid")]})
    route.fulfill(json={"outputs": [dict(item, id="runs/_universes/eu.json", name="eu listed", count=2)]})


def test_start_names_the_run_and_results_load_when_it_finishes(page):  # AC-78, AC-79
    acme = {"company_id": "c1", "name": "Acme", "ticker": None, "activity_id": "a1", "activity_name": "Batteries",
            "verdict": "include", "exposure_estimate": "significant", "confidence": 0.8, "revenue_exposure": None,
            "indirect_exposure": None, "flagged_for_review": False, "adjudicator_rationale": "r", "citations": []}
    page.route("**/api/taxonomies", lambda r: r.fulfill(json={"taxonomies": [TAXONOMY]}))
    page.route("**/api/taxonomies/tax1/versions", lambda r: r.fulfill(json={"versions": [TAXONOMY]}))
    page.route("**/api/taxonomies/tax1/versions/1/schema", lambda r: r.fulfill(json={"release_flag": True}))
    page.route("**/api/outputs?kind=*", _outputs)
    page.route("**/api/themes/runs", lambda r: r.fulfill(json={"run_id": "run_9", "company_count": 2}))
    Counter(page, "**/api/runs/run_9", lambda n: manifest("running" if n < 2 else "completed", run_id="run_9"))
    page.route(THEME_RESULTS.format("run_9"), lambda r: r.fulfill(json={"results": [acme]}))
    page.goto(f"{URL}/#/theme")
    page.get_by_role("button", name="Load", exact=True).click()
    page.get_by_label("Or pick a saved universe").select_option("runs/_universes/eu.json")
    page.get_by_role("button", name="Run screen against 2 companies").click()
    page.wait_for_function("() => location.hash === '#/theme/run_9'")
    assert page.get_by_label("Or pick a saved universe").input_value() == "runs/_universes/eu.json"
    page.get_by_role("cell", name="Acme").wait_for(timeout=10_000)
    page.get_by_role("button", name="Save 1 company as a universe").wait_for()  # AC-80


def test_one_company_saved(page):  # AC-80, AC-126
    one = {"company_id": "c1", "name": "Acme", "ticker": None, "activity_id": "a1", "activity_name": "Batteries",
           "verdict": "include", "exposure_estimate": "significant", "confidence": 0.8, "revenue_exposure": None,
           "indirect_exposure": None, "flagged_for_review": False, "adjudicator_rationale": "r", "citations": []}
    page.route("**/api/runs/run_t", lambda r: r.fulfill(json=manifest()))
    page.route(THEME_RESULTS.format("run_t"), lambda r: r.fulfill(json={"results": [one]}))
    page.route("**/api/universe/from-companies", lambda r: r.fulfill(json={"path": "x.json", "company_count": 1, "sample": []}))
    page.goto(f"{URL}/#/theme/run_t")
    page.get_by_role("button", name="Save 1 company as a universe").click()
    page.get_by_text("Saved 1 company as a universe.").wait_for()


def test_compare_lists_a_taxonomy_created_meanwhile(page):  # AC-83
    other = dict(TAXONOMY, taxonomy_id="tax2", name="Hydrogen later")
    Counter(page, "**/api/taxonomies", lambda n: {"taxonomies": [TAXONOMY] if n == 1 else [TAXONOMY, other]})
    page.goto(f"{URL}/#/taxonomy")
    page.get_by_role("button", name="Compare & merge").click()
    page.wait_for_function("() => [...document.querySelectorAll('option')].some(o => o.textContent.includes('Hydrogen later'))")


def test_writing_note_clears_the_action_error(page):  # AC-86
    def view(note):
        return {"dossier_id": "d1", "approved_round": None, "rounds": [{
            "round": 1, "taxonomy_version": 1, "plan_status": "approved", "proposal_run_id": None, "plan_approved_by": "a",
            "plan_approved_at": None, "sources": [], "note": note, "note_run_id": None, "search_unreachable": False}]}

    writing = {"status": "writing", "version": 1, "sections": {}, "dropped_items": 0}
    research = Counter(page, "**/api/dossiers/d1/research", lambda n: view(None if n == 1 else writing))
    page.route("**/api/dossiers/d1/research/note", lambda r: r.fulfill(status=504, json={"detail": "Gateway timeout"}))
    page.route("**/api/dossiers/d1", lambda r: r.fulfill(json={"dossier_id": "d1", "name": "Grid", "steps": []}))
    page.goto(f"{URL}/#/themes/d1/research")
    page.get_by_role("button", name="Write note").click()
    page.get_by_text("Writing the note…").wait_for()
    assert research.count >= 2
    assert page.get_by_text("Gateway timeout").count() == 0
