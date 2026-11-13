"""Showcase fixes for Argus, PR 2 (spec showcase-argus-fixes): the start page and steps 1 to 3, against the running app."""

import os
import re
from random import randint
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

TAG = uuid4().hex[:6]  # names and ids of this run, so what earlier runs left behind never matches


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.set_default_timeout(10_000)
        yield page
        browser.close()


def _ok(r):
    assert r.ok, r.text()
    return r.json()


def _isin() -> str:
    return "XS" + "".join(str(randint(0, 9)) for _ in range(10))  # the shape of an ISIN; check digits are not tested


def _flow(api, csv: str | None = None, **patch) -> str:
    fid = _ok(api.post(API + "/api/argus/flows"))["flow_id"]
    if csv:
        _ok(api.post(f"{API}/api/argus/flows/{fid}/companies/upload",
                     multipart={"file": {"name": "u.csv", "mimeType": "text/csv", "buffer": csv.encode()}}))
    if patch:
        _ok(api.patch(f"{API}/api/argus/flows/{fid}", data=patch))
    return fid


def _run(run_id, status, schema_name, version=2):
    at = "2026-10-01T10:00:00Z"
    return {"run_id": run_id, "run_type": "extraction", "status": status, "created_at": at, "updated_at": at,
            "params": {"started_by": "dev", "schema_name": schema_name, "schema_version": f"s:v{version}"}, "company_count": 3,
            "completed_count": 0, "failed_count": 0, "review_count": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0}


def _stub_start_page(page, runs, flows=None):
    page.route("**/api/runs*", lambda route: route.fulfill(json={"runs": runs}))
    page.route("**/api/review/items*", lambda route: route.fulfill(json={"items": []}))
    if flows is not None:
        page.route("**/api/argus/flows", lambda route: route.fulfill(json={"flows": flows}))


# --- start page ---


def test_a_filtered_start_page_says_so_and_offers_show_all(page):
    runs = [_run("r1", "running", "Green capex")]
    _stub_start_page(page, runs, flows=[])
    page.goto(URL + "/#/argus")
    table = page.get_by_role("table", name="Runs")
    table.get_by_text("Green capex v2").wait_for()
    process = page.get_by_role("region", name="Process")
    assert "Extractions at each step. Click a step to list only its extractions." in process.inner_text()  # AC-75
    assert page.locator(".argus-head").get_by_role("link", name="Walkthrough").get_attribute("href") == "#/argusWalkthrough"  # AC-80

    page.get_by_label("Only mine").check()
    process.get_by_role("link").nth(2).click()  # 3 Schema: no run is there
    page.get_by_text("Showing step 3 Schema only.").wait_for()  # AC-76
    assert "No run matches this filter." in table.inner_text() and "No runs yet" not in table.inner_text()  # AC-72
    table.get_by_role("button", name="Show all").click()  # AC-73
    table.get_by_text("Green capex v2").wait_for()
    assert not page.get_by_label("Only mine").is_checked()
    assert process.locator('[aria-pressed="true"]').count() == 0 and page.get_by_text("Showing step").count() == 0

    runs.clear()  # AC-74: nothing at all still reads as before
    page.reload()
    table.get_by_text("No runs yet.").wait_for()
    assert table.get_by_role("button", name="Start one").count() == 1 and "No run matches" not in table.inner_text()


def test_a_long_run_name_wraps_and_phone_cells_are_labelled(page):
    _stub_start_page(page, [_run("r1", "running", "Supercalifragilistic" * 3)], flows=[])
    page.goto(URL + "/#/argus")
    table = page.get_by_role("table", name="Runs")
    row = table.locator("tbody tr").first
    row.wait_for()
    box = row.get_by_role("link", name="Open").bounding_box()
    wrap = page.locator(".argus-start .table-wrap")
    assert box["x"] + box["width"] <= 1280 and wrap.evaluate("el => el.scrollWidth <= el.clientWidth")  # AC-77
    page.set_viewport_size({"width": 390, "height": 800})
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")  # AC-78
    assert wrap.evaluate("el => el.scrollWidth <= el.clientWidth")
    labels = row.locator("td").evaluate_all("tds => tds.map(td => td.dataset.label || '')")
    assert labels[:4] == ["Run", "Companies", "Step", "Status"]  # AC-79


def test_a_draft_row_names_its_companies_and_can_be_deleted(page):
    names = [f"Apple {TAG}", f"Microsoft {TAG}"] + [f"Co{i} {TAG}" for i in range(13)]
    fid = _flow(page.request, "name\n" + "\n".join(names) + "\n")
    _stub_start_page(page, [_run("r1", "completed", "Green capex", version=3)])
    page.goto(URL + "/#/argus")
    table = page.get_by_role("table", name="Runs")
    row = table.locator("tbody tr").filter(has=page.locator(f'a[href="#/argus/{fid}/1"]'))
    row.wait_for()
    text = row.inner_text()
    assert "New extraction" in text and re.search(rf"\d{{2}}:\d{{2}} · Apple {TAG}, Microsoft {TAG} \+13", text), text  # AC-67
    assert table.locator("tbody tr").filter(has_text="Green capex v3").get_by_role("button", name="Delete").count() == 0  # AC-71

    asked = []
    page.once("dialog", lambda d: (asked.append(d.message), d.dismiss()))
    row.get_by_role("button", name="Delete").click()
    assert asked == ["Delete this draft? Its company list and file choices are removed. Documents stay on the companies."]  # AC-68
    assert row.count() == 1  # AC-69
    page.once("dialog", lambda d: d.accept())
    row.get_by_role("button", name="Delete").click()
    row.wait_for(state="detached")  # AC-70
    assert page.request.get(f"{API}/api/argus/flows/{fid}").status == 404


def test_a_draft_without_a_company_is_not_listed(page):
    rows = page.get_by_role("table", name="Runs").locator("tbody tr")

    def listed():  # the table has at least one row once runs and drafts have loaded: a run, a draft or the empty line
        rows.first.wait_for()
        return rows.count()

    def flows():
        return {f["flow_id"]: f for f in _ok(page.request.get(API + "/api/argus/flows"))["flows"]}

    page.goto(URL + "/#/argus")
    n, before = listed(), flows()
    page.get_by_role("button", name="Start new extraction").click()  # AC-65
    page.wait_for_url(re.compile(r"#/argus/[0-9a-f]{32}/1$"))
    page.go_back()
    assert listed() == n

    page.goto(URL + "/#/transitionPlan")  # AC-66
    page.wait_for_url(re.compile(r"#/argus/[0-9a-f]{32}/1$"))
    page.goto(URL + "/#/argus")
    assert listed() == n
    made = [f for fid, f in flows().items() if fid not in before]
    assert len(made) == 2 and all(not f["companies"] for f in made)  # both drafts exist; they are only not listed


# --- step 1 and the flow shell ---


def test_step_1_rows_can_be_edited_and_removed_until_the_run_starts(page):
    apple, borealis, cedar, isin = f"Apple {TAG}", f"Borealis {TAG}", f"Cedar {TAG}", _isin()
    fid = _flow(page.request, f"name,isin\n{apple},{isin}\n{borealis},\n{cedar},\n")
    page.goto(f"{URL}/#/argus/{fid}/1")
    table = page.get_by_role("table", name="Companies")
    table.get_by_text(cedar).wait_for()
    rows = table.locator("tbody tr")
    assert rows.count() == 3
    for i in range(3):  # AC-56
        assert rows.nth(i).get_by_role("button", name="Edit").count() == 1 and rows.nth(i).get_by_role("button", name="Remove").count() == 1
    assert re.search(r"Central ID [0-9a-f]{8}-[0-9a-f]{4}-", rows.nth(0).inner_text())  # AC-60
    assert page.locator(".argus-flow .table-wrap").evaluate("el => el.scrollWidth <= el.clientWidth")  # Edit and Remove are in view

    rows.nth(0).get_by_role("button", name="Edit").click()  # AC-57
    form = page.get_by_role("form", name=f"Edit {apple}")
    values = {k: form.get_by_label(k, exact=True).input_value() for k in ("Name", "Ticker", "ISIN", "LEI", "CIK")}
    assert values == {"Name": apple, "Ticker": "", "ISIN": isin, "LEI": "", "CIK": ""}
    assert form.get_by_role("button", name="Save").count() == 1
    form.get_by_role("button", name="Cancel").click()

    row = rows.filter(has_text=borealis)
    assert "argus-row-await" in row.get_attribute("class")
    row.get_by_role("button", name="Edit").click()  # AC-58
    form = page.get_by_role("form", name=f"Edit {borealis}")
    new_isin = _isin()
    form.get_by_label("ISIN", exact=True).fill(new_isin)
    form.get_by_role("button", name="Save").click()
    row.get_by_text(f"ISIN {new_isin}").wait_for()
    assert "argus-row-await" not in (row.get_attribute("class") or "")

    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    rows.filter(has_text=cedar).get_by_role("button", name="Remove").click()  # AC-149
    page.get_by_role("button", name="Continue with 2 companies").wait_for()
    assert dialogs == [] and table.get_by_text(cedar).count() == 0

    def started(route):  # AC-59: the flow as it reads once it has a run
        r = route.fetch()
        route.fulfill(response=r, json={**r.json(), "run_id": "run-x"})

    page.route(f"**/api/argus/flows/{fid}", started)
    page.reload()
    table.get_by_text(apple).wait_for()
    assert table.get_by_role("button", name="Edit").count() == 0 and table.get_by_role("button", name="Remove").count() == 0


def test_an_identity_run_that_ends_updates_step_1_without_a_reload(page):
    fid = _flow(page.request, f"name\nAcme {TAG}\n")
    state = {"status": "running"}

    def flow(route):  # the flow while, and after, its identity run: the server applies the result when the run has ended
        r = route.fetch()
        body = {**r.json(), "identity_run_id": "id-run", "identity": {"run_id": "id-run", "status": state["status"]}}
        if state["status"] == "completed":
            body["rows"] = [{**row, "problem": None} for row in body["rows"]]
        route.fulfill(response=r, json=body)

    page.route(f"**/api/argus/flows/{fid}", flow)
    page.goto(f"{URL}/#/argus/{fid}/1")
    page.get_by_text("Identity run started.").wait_for()
    assert page.locator(".argus-row-await").count() == 1
    state["status"] = "completed"
    page.wait_for_function("() => !document.querySelector('.argus-row-await')", timeout=10_000)  # AC-62
    page.get_by_text("Identities resolved.").wait_for()  # AC-63


def test_saved_universes_with_the_same_name_differ_by_their_time(page):
    outs = [{"kind": "universe", "id": f"/u/{i}", "name": "Tech (3 companies)", "version": None, "as_of": f"2026-11-12T1{i}:15:00+00:00",
             "status": "saved", "by": None, "count": 3, "used_by": []} for i in (0, 1)]
    page.route("**/api/outputs?kind=universe", lambda route: route.fulfill(json={"outputs": outs}))
    page.goto(f"{URL}/#/argus/{_flow(page.request)}/1")
    options = page.get_by_label("Or pick a saved universe").locator("option")
    options.nth(2).wait_for(state="attached")
    texts = options.all_inner_texts()[1:]
    assert len(set(texts)) == 2 and all(re.search(r" \d{2}:\d{2}$", t) for t in texts), texts  # AC-61


def test_a_step_that_does_not_exist_goes_to_the_furthest_step(page):
    fid = _flow(page.request, f"name\nAcme {TAG}\n", step=2)
    for bad in ("7", "2.5", "-1"):  # AC-104
        page.goto(f"{URL}/#/argus/{fid}/{bad}")
        page.wait_for_function(f"() => location.hash === '#/argus/{fid}/2'")
        page.get_by_role("table", name="Files").wait_for()
        assert page.get_by_role("navigation", name="Steps").get_by_role("listitem").nth(1).get_attribute("aria-current") == "step"
    new = _flow(page.request)  # AC-105: a real step the flow has not reached still opens
    page.goto(f"{URL}/#/argus/{new}/3")
    page.get_by_role("region", name="What to extract").wait_for()
    assert page.evaluate("location.hash") == f"#/argus/{new}/3"


def test_an_error_banner_has_no_status_number(page):
    fid = _flow(page.request, step=2, source="filings")
    page.goto(f"{URL}/#/argus/{fid}/2")
    page.get_by_role("button", name="Find documents").click()
    alert = page.get_by_role("alert")
    alert.wait_for()
    assert alert.inner_text() == "Add companies in step 1 first."  # AC-106


FOCUSED = "(x) => (document.activeElement.getAttribute('aria-label') || document.activeElement.getAttribute('href') || document.activeElement.tagName) === x"


def test_row_actions_name_their_row_and_keep_keyboard_focus(page):
    api = page.request
    a, b, c = (f"{n} {TAG}f" for n in ("Ash", "Birch", "Cedar"))
    fid = _flow(api, f"name\n{a}\n{b}\n{c}\n")
    page.goto(f"{URL}/#/argus/{fid}/1")
    table = page.get_by_role("table", name="Companies")
    table.get_by_text(c).wait_for()
    for name in (a, b, c):  # a screen reader's button list tells the rows apart
        assert table.get_by_role("button", name=f"Edit {name}", exact=True).count() == 1
        assert table.get_by_role("button", name=f"Remove {name}", exact=True).count() == 1
    assert table.get_by_role("columnheader", name="Actions").count() == 1

    table.get_by_role("button", name=f"Edit {a}", exact=True).press("Enter")
    page.get_by_role("form", name=f"Edit {a}").get_by_role("button", name="Cancel").press("Enter")
    page.wait_for_function(FOCUSED, arg=f"Edit {a}")  # Cancel: back on the row's Edit
    table.get_by_role("button", name=f"Edit {a}", exact=True).press("Enter")
    form = page.get_by_role("form", name=f"Edit {a}")
    form.get_by_label("Name", exact=True).fill(f"{a} Corp")
    form.get_by_role("button", name="Save").press("Enter")
    page.wait_for_function(FOCUSED, arg=f"Edit {a} Corp")  # Save: the same row's Edit
    table.get_by_role("button", name=f"Remove {b}", exact=True).press("Enter")
    page.wait_for_function(FOCUSED, arg=f"Edit {c}")  # Remove: the next row's first action
    table.get_by_role("button", name=f"Remove {c}", exact=True).press("Enter")
    page.wait_for_function(FOCUSED, arg=f"Edit {a} Corp")  # no next row: the one before
    table.get_by_role("button", name=f"Remove {a} Corp", exact=True).press("Enter")
    page.wait_for_function(FOCUSED, arg="Companies")  # no row left: the table itself

    older, newer = f"Dee {TAG}f", f"Eff {TAG}f"  # start page: newest first, so the older draft is the next row
    d1 = _flow(api, f"name\n{older}\n")
    _flow(api, f"name\n{newer}\n")
    page.on("dialog", lambda d: d.accept())
    page.goto(URL + "/#/argus")
    delete = page.get_by_role("table", name="Runs").get_by_role("button", name=f"Delete draft {newer}", exact=True)
    delete.press("Enter")
    page.wait_for_function(FOCUSED, arg=f"#/argus/{d1}/1")  # Delete: the next row's Open
    _ok_status = api.post(f"{API}/api/argus/flows/{d1}/discard").status
    assert _ok_status == 204


def test_phone_labels_stay_on_one_line(page):
    fid = _flow(page.request, f"name,isin\nApple {TAG}p,{_isin()}\n")
    _stub_start_page(page, [_run("r1", "running", "Supercalifragilistic" * 3)], flows=[])  # a value that squeezes its label
    page.set_viewport_size({"width": 390, "height": 844})
    # the label is as wide as its text needs, so no word of it is broken
    one_line = """td => {
        const s = getComputedStyle(td, '::before'), c = document.createElement('canvas').getContext('2d');
        c.font = `${s.fontSize} ${s.fontFamily}`;
        return parseFloat(s.width) >= c.measureText(td.dataset.label).width - 1;
    }"""
    page.goto(URL + "/#/argus")
    cell = page.get_by_role("table", name="Runs").locator('td[data-label="Run"]').first
    cell.wait_for()
    assert cell.evaluate(one_line)  # not "Ru / n"
    page.goto(f"{URL}/#/argus/{fid}/1")
    cell = page.get_by_role("table", name="Companies").locator('td[data-label="Company"]').first
    cell.wait_for()
    assert cell.evaluate(one_line)  # not "Compa / ny"


# --- step 2 ---


def test_step_2_keeps_a_passing_upload_and_labels_type_and_state(page, tmp_path):
    a, b = f"Applewood {TAG}", f"Birchwood {TAG}"
    fid = _flow(page.request, f"name\n{a}\n{b}\n", step=2, reporting_year=2025, source="upload")
    page.goto(f"{URL}/#/argus/{fid}/2")
    page.get_by_label(a, exact=True).wait_for()
    imp = page.get_by_label("From the import folder (not available yet)", exact=True)  # AC-86
    assert imp.is_disabled() and "Available once" not in page.locator(".argus-sources").inner_text()
    heights = page.locator(".argus-source").evaluate_all("ls => ls.map(l => l.getBoundingClientRect().height)")
    assert heights[1] == heights[0]  # one line, like its neighbour

    files = page.get_by_role("table", name="Files")
    for name, stem in ((a, "a"), (b, "b")):
        pdf = make_pdf(tmp_path / f"{stem}-2025.pdf", [f"{name} Annual Report 2025", FILLER], n_pages=2)
        page.get_by_label(name, exact=True).set_input_files(str(pdf))
        files.get_by_text(pdf.name).wait_for()
    go = page.get_by_role("button", name="Continue with 2 files for 2 companies")  # AC-81: nothing else was clicked
    go.wait_for()
    assert go.is_enabled()
    assert files.locator("tr", has_text="a-2025.pdf").locator('td[data-label="Type"]').inner_text() == "Annual report"  # AC-83

    page.locator("#argus-upload-type").select_option(label="Sustainability report")
    other = make_pdf(tmp_path / "other.pdf", [f"Someone Else {TAG} Report 2025", FILLER], n_pages=2)
    page.get_by_label(a, exact=True).set_input_files(str(other))
    row = files.locator("tr", has_text="other.pdf")
    row.wait_for()
    assert row.locator('td[data-label="Type"]').inner_text() == "Sustainability report"  # AC-84
    keep = row.locator('td[data-label="In this extraction"]')  # AC-82: its check failed
    assert "Not decided" in keep.inner_text()
    assert keep.get_by_role("button", name="Keep").count() == 1 and keep.get_by_role("button", name="Remove").count() == 1


# --- step 3 ---


def _fields(prefix, n, look_in="Annual report"):
    return [{"field_id": f"{prefix}{i}_{TAG}", "name": f"{prefix} field {i}", "description": f"Meaning {i}", "data_type": "number",
             "extraction_instructions": look_in} for i in range(n)]


def _schema(api, key, name, fields):
    return _ok(api.post(API + "/api/extraction/schemas", data={"schema_id": f"sch_{key}_{TAG}", "name": name, "fields": fields}))


def _choose(page, name):
    page.get_by_role("region", name="What to extract").get_by_role("button", name=re.compile(re.escape(name))).click()
    table = page.get_by_role("table", name="Fields to extract")
    table.wait_for()
    return table


def test_a_saved_schema_with_long_texts_keeps_its_layout(page):
    look_in = ("Annual report, sustainability report and the notes on capital expenditure. " * 8)[:600].strip()
    name = f"Wraps{TAG}".ljust(60, "x")
    fields = _fields("w", 4, look_in)
    fields[0]["name"] = "Green capex share"  # a name of several words still leaves the table inside its box
    _schema(page.request, "wide", name, fields)
    page.goto(f"{URL}/#/argus/{_flow(page.request)}/3")
    table = _choose(page, name)
    table.get_by_text("Meaning 3").wait_for()
    widths = table.locator("thead th").evaluate_all("ths => ths.map(th => th.getBoundingClientRect().width)")
    assert widths[3] >= 240 and widths[4] >= 240, widths  # AC-87
    assert widths[0] >= 96, widths  # the Field column holds a name of a few words in two lines, not six
    assert page.locator(".argus-schema-fields .table-wrap").evaluate("el => el.scrollWidth <= el.clientWidth")  # and nothing is cut off
    cells = table.locator('td[data-label="Look in"]')
    for i in range(4):  # AC-88
        assert cells.nth(i).get_by_role("button", name="Show more").count() == 1
        lines = cells.nth(i).locator(".argus-clamp").evaluate("el => el.getBoundingClientRect().height / parseFloat(getComputedStyle(el).fontSize)")
        assert lines <= 3 * 1.8, lines
    cells.nth(0).get_by_role("button", name="Show more").click()  # AC-89
    assert look_in in cells.nth(0).inner_text() and cells.nth(0).get_by_role("button", name="Show less").count() == 1
    assert cells.nth(0).locator(".argus-clamp").count() == 0

    pick = page.get_by_role("region", name="What to extract")  # AC-90
    item = pick.locator("li").filter(has_text=name)
    card, box = pick.bounding_box(), item.bounding_box()
    assert box["x"] + box["width"] <= card["x"] + card["width"] and "4 fields" in item.inner_text()
    assert item.get_by_role("button").evaluate("el => el.scrollWidth <= el.clientWidth")
    page.set_viewport_size({"width": 390, "height": 800})  # the long name does not widen a phone's page either
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def _add_field(page, name, position):
    page.get_by_role("button", name="Add field").click()
    page.get_by_label(f"Field {position} name").fill(name)


def _save_version(page, expect):
    page.get_by_role("button", name=re.compile(r"^Save as v\d+$")).click()
    table = page.get_by_role("table", name="Fields to extract")
    table.get_by_text(expect, exact=True).wait_for()
    return table


def test_added_fields_get_ids_no_other_schema_or_field_has(page):
    api = page.request
    alpha, beta, gamma = f"Alpha {TAG}", f"Beta {TAG}", f"Gamma {TAG}"
    for key, name in (("a", alpha), ("b", beta), ("g", gamma)):
        _schema(api, key, name, _fields(key, 2))
    page.goto(f"{URL}/#/argus/{_flow(api)}/3")
    page.on("dialog", lambda d: d.accept())  # Release asks first

    _choose(page, alpha)
    _add_field(page, "Revenue", 3)
    _save_version(page, "Revenue")
    page.get_by_role("button", name="Release", exact=True).click()
    page.get_by_role("heading", name=re.compile(rf"{alpha}.*released")).wait_for()
    _choose(page, beta)
    _add_field(page, "Capex", 3)
    table = _save_version(page, "Capex")  # AC-91
    assert table.locator("tbody tr").count() == 3 and page.get_by_role("alert").count() == 0
    table = _choose(page, alpha)  # AC-92
    table.get_by_text("Revenue", exact=True).wait_for()
    assert table.locator("tbody tr").nth(2).locator('td[data-label="Field"]').inner_text() == "Revenue"

    _choose(page, gamma)  # AC-94: two added, the first left blank
    page.get_by_role("button", name="Add field").click()
    _add_field(page, "Second", 4)
    _save_version(page, "Second")
    _add_field(page, "X", 4)
    _save_version(page, "X")
    ids = [f["field_id"] for f in _ok(api.get(f"{API}/api/extraction/schemas/sch_g_{TAG}"))["fields"]]
    assert len(ids) == 4 and len(set(ids)) == 4, ids


def test_release_asks_first(page, tmp_path):
    api = page.request
    names = [f"{n} {TAG}" for n in ("Ash", "Beech", "Cherry")]
    fid = _flow(api, "name\n" + "\n".join(names) + "\n", reporting_year=2025, step=3)
    for i, c in enumerate(_ok(api.get(f"{API}/api/argus/flows/{fid}"))["companies"]):
        pdf = make_pdf(tmp_path / f"r{i}.pdf", [f"{c['name']} Annual Report 2025", FILLER], n_pages=2).read_bytes()
        _ok(api.post(f"{API}/api/argus/flows/{fid}/documents/upload", multipart={
            "company_id": c["company_id"], "doc_type": "10-K", "file": {"name": f"r{i}.pdf", "mimeType": "application/pdf", "buffer": pdf}}))
    s = f"Release {TAG}"
    _schema(api, "rel", s, _fields("r", 2))
    page.goto(f"{URL}/#/argus/{fid}/3")
    _choose(page, s)
    trial = page.get_by_role("button", name=f"Try {s} on 1 company")
    trial.wait_for()
    asked = []
    page.once("dialog", lambda d: (asked.append(d.message), d.dismiss()))
    page.get_by_role("button", name="Release", exact=True).click()
    assert asked == [f"Release {s} v1? A released version cannot be changed or withdrawn. It then extracts all 3 companies."]  # AC-95
    assert trial.count() == 1 and page.get_by_role("button", name="Release", exact=True).count() == 1  # AC-96
    page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Release", exact=True).click()
    page.get_by_role("button", name=f"Extract {s} v1 for 3 companies").wait_for()  # AC-97


def test_an_unsaved_draft_survives_a_reload_and_stays_in_its_flow(page):
    # as the server drafts them: with the list fields the editor reads
    drafted = {"schema_id": f"sch_d_{TAG}", "name": f"Drafted {TAG}",
               "fields": [{**f, "unit": None, "required": False, "source_doc_types": [], "seed_keywords": []} for f in _fields("d", 2)]}
    page.route("**/api/extraction/schemas/draft", lambda route: route.fulfill(json=drafted))
    page.route("**/api/extraction/schemas/suggest-rules", lambda route: route.fulfill(json={"rules": [], "helper_fields": []}))
    first, second = _flow(page.request), _flow(page.request)
    words = page.get_by_label("What should be extracted?")
    page.goto(f"{URL}/#/argus/{first}/3")
    words.fill("Green capex and its share")
    page.get_by_role("button", name="Draft fields").click()
    page.get_by_label("Field 2 name").wait_for()
    page.wait_for_function("() => !document.body.innerText.includes('Suggesting rules')")

    page.reload()  # AC-98
    page.get_by_label("Field 2 name").wait_for()
    assert [page.get_by_label(f"Field {i} name").input_value() for i in (1, 2)] == ["d field 0", "d field 1"]
    assert words.input_value() == "Green capex and its share"
    assert "not saved" in page.get_by_role("heading", name=re.compile(f"Drafted {TAG}")).inner_text()

    page.goto(f"{URL}/#/argus/{second}/3")  # AC-100
    page.get_by_text("Choose a saved schema or a template").wait_for()
    assert page.get_by_label("Field 1 name").count() == 0 and words.input_value() == ""

    page.goto(f"{URL}/#/argus/{first}/3")  # AC-99
    page.get_by_label("Field 2 name").wait_for()
    page.get_by_role("button", name="Save as a draft schema").click()
    table = page.get_by_role("table", name="Fields to extract")
    table.get_by_text("d field 1").wait_for()
    page.reload()
    table.get_by_text("d field 1").wait_for()
    assert page.get_by_text("not saved").count() == 0 and page.get_by_label("Field 1 name").count() == 0


def test_settings_are_disabled_while_a_save_is_in_flight(page):
    fid = _flow(page.request)
    page.goto(f"{URL}/#/argus/{fid}/3")
    page.locator("details.argus-settings summary").click()
    held = []  # the save stays in flight until continued
    page.route(f"**/api/argus/flows/{fid}", lambda route: held.append(route) if route.request.method == "PATCH" else route.continue_())
    batch = page.get_by_label(re.compile("Batch"))
    batch.click()
    page.wait_for_function("() => document.querySelector('#argus-evidence').disabled")  # AC-101
    assert batch.is_disabled()
    held[0].continue_()
    page.wait_for_function("() => !document.querySelector('#argus-evidence').disabled")
    assert not batch.is_disabled()


def test_a_chosen_schema_that_no_longer_exists_is_cleared_with_a_message(page):
    api = page.request
    fid = _flow(api, schema_choice={"kind": "schema", "schema_id": f"sch_gone_{TAG}", "version": 1, "profile": None})
    page.goto(f"{URL}/#/argus/{fid}/3")
    page.get_by_text("The schema chosen earlier no longer exists. Choose another.").wait_for()  # AC-102
    page.get_by_role("button", name="Choose what to extract").wait_for()
    page.wait_for_function("async (u) => (await (await fetch(u)).json()).schema_choice === null", arg=f"{API}/api/argus/flows/{fid}")  # AC-103
