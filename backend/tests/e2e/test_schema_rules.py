"""Schema screen Rules list (schema-rules spec AC-39..AC-57, AC-71) against the running app.

Draft and suggest-rules are stubbed with Playwright routing, so the suggestions are fixed. Starting a
run (AC-56, AC-71) also stubs the company list, its readiness and the start call, and reads the body.
"""

import os
import re

import pytest

from arp.config import Settings
from arp.schemas.rules import Condition, ThresholdRule
from tests.rules_fixtures import R1, R2, R4, R5, schema_f

URL = os.environ.get("ARP_E2E_URL")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

F = schema_f().model_dump(mode="json")
CONFIRM = re.compile(r"rule suggestions? waiting|Confirm schema")
# Two more rules on `ambition` that read `total` (AC-45) and `year` (AC-49).
R_TOTAL = ThresholdRule(rule_id="RT", kind="threshold", conditions=[Condition(field="total", op=">=", value=100)])
R_YEAR = ThresholdRule(rule_id="RY", kind="threshold", when=True, conditions=[Condition(field="year", op="<=", value=2040)])
R5_SENTENCE = "Green capex share should equal Green capex ÷ Total capex × 100, within 1."
R1_SENTENCE = "When Halving target is YES: needs Target reduction >= 50 and Target year <= 2030."
R2_SENTENCE = "When Net zero by 2050 is YES: needs Net-zero target to be YES."
R4_SENTENCE = "When Scope 1 target is YES: Target type must not be combined."


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1280, "height": 600})
        page.set_default_timeout(10_000)
        yield page
        browser.close()


def schema(drop=()):
    return {**F, "fields": [f for f in F["fields"] if f["field_id"] not in drop]}


def field(fid):
    return next(f for f in F["fields"] if f["field_id"] == fid)


def suggestions(*rules, helpers=()):
    return {"rules": [{"field_id": fid, "rule": r.model_dump(mode="json")} for fid, r in rules], "helper_fields": [field(h) for h in helpers]}


def open_schema(page, drafted, *responses):
    """Drafts `drafted`; suggest-rules answers the n-th call with responses[n] (the last one repeats)."""
    calls = []

    def suggest(route):
        calls.append(route.request.post_data_json)
        route.fulfill(json=responses[min(len(calls), len(responses)) - 1])

    page.route("**/api/extraction/schemas/draft", lambda route: route.fulfill(json=drafted))
    page.route("**/api/extraction/schemas/suggest-rules", suggest)
    page.goto(URL)
    page.wait_for_load_state("networkidle")
    nav = page.get_by_role("navigation").first
    nav.get_by_text("All screens").click()
    nav.get_by_text("Extraction", exact=True).click()
    page.get_by_role("tab", name="4. Schema").click()
    page.get_by_role("button", name="Draft extraction schema").click()
    page.get_by_role("button", name="+ Add a rule").wait_for()
    page.wait_for_function("() => !document.body.innerText.includes('Suggesting rules')")
    return calls


def rules_list(page):
    return page.get_by_role("list", name="Rules")


def item(page, sentence):
    return rules_list(page).get_by_role("listitem").filter(has_text=sentence)


def field_names(page):
    return page.locator(".activity-editor input[aria-label$=' name']").evaluate_all("els => els.map(e => e.value)")


def field_block(page, fid):
    """The fields-editor block of `fid`, by its position in the drafted schema."""
    names = field_names(page)
    return page.locator(".activity-editor").nth(names.index(field(fid)["name"]))


def confirm(page):
    return page.get_by_role("button", name=CONFIRM)


def start_run(page):
    """Picks one company (stubbed as ready), starts extraction and returns the posted body."""
    page.route("**/api/universe/from-companies", lambda r: r.fulfill(json={"path": "e2e.csv", "company_count": 1, "sample": []}))
    ready = {"on_disk": 1, "registered": 1, "parsed": 1, "doc_types": ["annual_report"], "last_seen_at": None, "ready": True}
    acme = {"company_id": "acme", "name": "ACME", "ticker": None, "website": None}
    page.route("**/api/documents/readiness", lambda r: r.fulfill(json={"ready": [{**acme, "readiness": ready}], "onboard": [], "readiness": {}}))
    bodies = []

    def start(route):
        bodies.append(route.request.post_data_json)
        route.fulfill(json={"run_id": "run_e2e", "company_count": 1, "run_type": "extraction"})

    page.route("**/api/extraction/start", start)
    page.get_by_role("tab", name="1. Companies").click()
    page.get_by_role("button", name="Single company").click()
    page.get_by_label("Company name").fill("ACME")
    page.get_by_role("button", name="Use this company").click()
    page.get_by_text("ACME selected · 1 ready · 0 to onboard").wait_for()
    page.get_by_role("tab", name="5. Extract").click()
    page.get_by_role("button", name="Start extraction").click()
    page.wait_for_function("() => document.body.innerText.includes('Starting') || document.body.innerText.includes('companies processed')")
    assert len(bodies) == 1
    return bodies[0]["datapoint_schema"]


def test_ac39_waiting_suggestion_shows_sentence_and_actions(page):
    open_schema(page, schema(drop=["pct"]), suggestions(("ambition", R1()), helpers=["pct"]))
    it = item(page, R1_SENTENCE)
    for name in ("Accept", "Edit", "Drop"):
        assert it.get_by_role("button", name=name, exact=True).is_visible()


def test_ac40_to_ac42_confirm_counts_waiting_suggestions(page):
    open_schema(page, schema(), suggestions(("ambition", R1()), ("nz2050", R2())))
    assert confirm(page).inner_text() == "2 rule suggestions waiting"
    assert confirm(page).is_disabled()

    item(page, R1_SENTENCE).get_by_role("button", name="Accept").click()
    assert confirm(page).inner_text() == "1 rule suggestion waiting"
    assert confirm(page).is_disabled()

    item(page, R2_SENTENCE).get_by_role("button", name="Drop").click()
    assert confirm(page).inner_text() == f"Confirm schema ({len(F['fields'])} fields)"
    assert confirm(page).is_enabled()


def test_ac43_ac44_accept_adds_the_helper_field_once(page):
    open_schema(page, schema(drop=["total"]), suggestions(("share", R5()), helpers=["total"]))
    assert "Total capex" not in field_names(page)

    item(page, R5_SENTENCE).get_by_role("button", name="Accept").click()
    assert field_names(page).count("Total capex") == 1
    it = item(page, R5_SENTENCE)
    assert it.get_by_text("Accepted", exact=True).is_visible()
    assert it.get_by_role("button", name="Edit").is_visible()
    assert it.get_by_role("button", name="Drop").is_visible()
    assert it.get_by_role("button", name="Accept").count() == 0


def test_ac45_two_suggestions_with_one_helper_add_it_once(page):
    open_schema(page, schema(drop=["total"]), suggestions(("share", R5()), ("ambition", R_TOTAL), helpers=["total"]))
    item(page, R5_SENTENCE).get_by_role("button", name="Accept").click()
    item(page, "Needs Total capex >= 100.").get_by_role("button", name="Accept").click()
    assert field_names(page).count("Total capex") == 1


def test_ac46_drop_on_waiting_adds_nothing(page):
    open_schema(page, schema(drop=["total"]), suggestions(("share", R5()), helpers=["total"]))
    before = field_names(page)
    item(page, R5_SENTENCE).get_by_role("button", name="Drop").click()
    assert item(page, R5_SENTENCE).count() == 0
    assert field_names(page) == before


def test_ac47_drop_on_accepted_keeps_the_helper(page):
    open_schema(page, schema(drop=["total"]), suggestions(("share", R5()), helpers=["total"]))
    item(page, R5_SENTENCE).get_by_role("button", name="Accept").click()
    item(page, R5_SENTENCE).get_by_role("button", name="Drop").click()
    assert item(page, R5_SENTENCE).count() == 0
    assert field_names(page).count("Total capex") == 1


def test_ac48_editing_rerenders_the_sentence_before_saving(page):
    open_schema(page, schema(drop=["pct"]), suggestions(("ambition", R1()), helpers=["pct"]))
    item(page, R1_SENTENCE).get_by_role("button", name="Edit").click()
    rules_list(page).get_by_label("Condition 1 value").fill("40")
    assert rules_list(page).get_by_text(
        "When Halving target is YES: needs Target reduction >= 40 and Target year <= 2030.", exact=True
    ).is_visible()


def test_ac49_marker_counts_accepted_and_waiting(page):
    open_schema(page, schema(), suggestions(("ambition", R1()), ("ambition", R_YEAR)))
    item(page, R1_SENTENCE).get_by_role("button", name="Accept").click()
    assert field_block(page, "ambition").get_by_role("button", name="2 rules · 1 waiting").is_visible()


def test_ac50_marker_click_scrolls_to_the_fields_first_rule(page):
    open_schema(page, schema(), suggestions(("ambition", R1()), ("ambition", R_YEAR)))
    first = item(page, R1_SENTENCE)
    in_view = "e => { const r = e.getBoundingClientRect(); return r.top >= 0 && r.bottom <= window.innerHeight; }"
    page.evaluate("window.scrollTo(0, 0)")
    marker = field_block(page, "ambition").get_by_role("button", name="2 rules · 2 waiting")
    marker.scroll_into_view_if_needed()
    assert not first.evaluate(in_view)
    marker.click()
    page.wait_for_timeout(300)
    assert first.evaluate(in_view)


def test_ac51_field_without_rules_shows_no_marker(page):
    open_schema(page, schema(), suggestions(("ambition", R1())))
    assert "rule" not in field_block(page, "nz").inner_text()
    assert field_block(page, "nz").get_by_role("button").count() == 0


def test_ac52_field_read_by_an_accepted_rule_says_so(page):
    open_schema(page, schema(), suggestions(("ambition", R1())))
    item(page, R1_SENTENCE).get_by_role("button", name="Accept").click()
    assert field_block(page, "pct").get_by_text("used by a rule").is_visible()


def test_ac53_fields_editor_has_no_rule_controls(page):
    open_schema(page, schema(), suggestions(("ambition", R1()), ("nz2050", R2())))
    item(page, R1_SENTENCE).get_by_role("button", name="Accept").click()
    editor = page.locator(".activity-editor")
    for name in ("Accept", "Edit", "Drop"):
        assert editor.get_by_role("button", name=name, exact=True).count() == 0
    assert editor.locator("select, input[type=number]").count() == 0


def test_ac54_add_a_rule_saves_an_accepted_rule(page):
    open_schema(page, schema(), suggestions())
    page.get_by_role("button", name="+ Add a rule").click()
    rules = rules_list(page)
    rules.get_by_label("Checked field").select_option(label="Halving target")
    rules.get_by_label("When").select_option(label="YES")
    rules.get_by_label("Kind").select_option("threshold")
    rules.get_by_label("Condition 1 field").select_option(label="Target reduction")
    rules.get_by_label("Condition 1 operator").select_option(">=")
    rules.get_by_label("Condition 1 value").fill("50")
    rules.get_by_role("button", name="Save").click()
    it = item(page, "When Halving target is YES: needs Target reduction >= 50.")
    assert it.get_by_text("Accepted", exact=True).is_visible()


def test_ac55_suggest_again_hides_accepted_and_dropped_matches(page):
    again = suggestions(
        ("ambition", R1().model_copy(update={"rule_id": "N1"})),
        ("nz2050", R2().model_copy(update={"rule_id": "N2"})),
        ("s1", R4().model_copy(update={"rule_id": "N4"})),
    )
    calls = open_schema(page, schema(), suggestions(("ambition", R1()), ("nz2050", R2())), again)
    item(page, R1_SENTENCE).get_by_role("button", name="Accept").click()
    item(page, R2_SENTENCE).get_by_role("button", name="Drop").click()
    page.get_by_role("button", name="Suggest again").click()
    item(page, R4_SENTENCE).wait_for()
    assert len(calls) == 2
    assert item(page, R1_SENTENCE).count() == 1
    assert item(page, R1_SENTENCE).get_by_text("Accepted", exact=True).is_visible()
    assert item(page, R4_SENTENCE).get_by_role("button", name="Accept").is_visible()
    assert item(page, R2_SENTENCE).count() == 0


def test_ac56_all_dropped_runs_without_rules(page):
    open_schema(page, schema(), suggestions(("ambition", R1()), ("nz2050", R2())))
    item(page, R1_SENTENCE).get_by_role("button", name="Drop").click()
    item(page, R2_SENTENCE).get_by_role("button", name="Drop").click()
    confirm(page).click()
    sent = start_run(page)
    assert all(f.get("rules") in (None, []) for f in sent["fields"])
    assert [f["field_id"] for f in sent["fields"]] == [f["field_id"] for f in F["fields"]]


def test_ac57_editing_a_confirmed_schema_asks_again(page):
    open_schema(page, schema(), suggestions())
    confirm(page).click()
    assert confirm(page).count() == 0
    page.get_by_label("Field 1 name").fill("Halving target (edited)")
    assert confirm(page).inner_text() == f"Confirm schema ({len(F['fields'])} fields)"
    assert confirm(page).is_enabled()


def test_ac71_accepted_rule_and_helper_reach_the_run(page):
    open_schema(page, schema(drop=["pct"]), suggestions(("ambition", R1()), helpers=["pct"]))
    item(page, R1_SENTENCE).get_by_role("button", name="Accept").click()
    confirm(page).click()
    sent = start_run(page)
    ambition = next(f for f in sent["fields"] if f["field_id"] == "ambition")
    assert ambition["rules"] == [R1().model_dump(mode="json")]
    assert [f["field_id"] for f in sent["fields"]].count("pct") == 1

