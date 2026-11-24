"""Spec number-inputs-review-ui: Index Builder inputs keep what is typed; selects send what they show."""

import pytest

from arp.config import Settings
from tests.e2e.test_showcase_themes_screens import URL, pytestmark  # noqa: F401 - pytestmark marks this module


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(10_000)
        yield page
        browser.close()


def _empty_ib(page):
    page.goto(f"{URL}/#/index")
    page.get_by_role("button", name="Empty", exact=True).click()


def _preview_body(page):
    with page.expect_request("**/api/index/run") as req:
        page.get_by_role("button", name="Preview", exact=True).click()
    return req.value.post_data_json


def test_comma_list_keeps_the_typed_comma_until_blur(page):
    _empty_ib(page)
    page.get_by_role("button", name="+ Category allow / deny").click()
    box = page.get_by_label("Allow only (comma separated)")
    box.click()
    box.press_sequentially("Energy,")
    assert box.input_value() == "Energy,"
    box.fill("")
    box.press_sequentially("Energy,, Utilities ,")
    box.press("Tab")
    assert box.input_value() == "Energy, Utilities"
    assert _preview_body(page)["spec"]["screens"][0]["allow"] == ["Energy", "Utilities"]


def test_multipliers_textarea_keeps_unfinished_lines_until_blur(page):
    _empty_ib(page)
    page.get_by_role("button", name="+ Category multiplier table").click()
    area = page.get_by_label('Multipliers, one "value = factor" per line')
    area.click()
    area.press_sequentially("Energy")
    assert area.input_value() == "Energy"
    area.press_sequentially(" = 1.5\nOil")
    area.press("Tab")
    assert area.input_value() == "Energy = 1.5"
    assert _preview_body(page)["spec"]["tilts"][0]["multipliers"] == {"Energy": 1.5}


def test_a_cleared_number_stays_empty_while_typing_and_defaults_on_blur(page):
    _empty_ib(page)
    page.get_by_role("button", name="+ Category multiplier table").click()
    box = page.get_by_label("Default multiplier")
    box.click()
    box.press("Control+a")
    box.press("Backspace")
    assert box.input_value() == ""
    box.press("7")
    assert box.input_value() == "7"
    assert _preview_body(page)["spec"]["tilts"][0]["default_multiplier"] == 7
    page.get_by_role("tab", name="Compose").click()
    box = page.get_by_label("Default multiplier")
    box.click()
    box.press("Control+a")
    box.press("Backspace")
    box.press("Tab")
    assert box.input_value() == "1"


def test_selects_send_what_they_show(page):
    _empty_ib(page)
    page.get_by_label("Scheme").select_option("metric")
    shown = page.locator("label.field-label:has-text(\"Field\") select").first.input_value()
    assert _preview_body(page)["spec"]["base_weighting"]["field"] == shown
    page.get_by_role("tab", name="Compose").click()
    page.get_by_role("button", name="+ Metric tilt").click()
    page.get_by_label("Normalisation").select_option("group_max")
    within = page.get_by_label("Within").input_value()
    group_by = _preview_body(page)["spec"]["tilts"][0]["group_by"]
    assert group_by == within and group_by != "none"
