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
