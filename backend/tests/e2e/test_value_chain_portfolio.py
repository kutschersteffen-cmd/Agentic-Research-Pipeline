"""Value Chain Explorer Portfolio view (value-chain-links-overlays spec AC-38 to AC-43c) against the running app.

The value-chain, portfolio-list and taxonomy calls are answered by an in-process API on Fixture V and
store S linked (tests/test_value_chain_links.py), so saves and resets go through the real routes.
"""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from arp.config import Settings
from tests.test_value_chain_links import env, linked  # noqa: F401  (fixtures)

URL = os.environ.get("ARP_E2E_URL")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

SCREENSHOT = Path(__file__).resolve().parents[2] / "test-results" / "value-chain-portfolio.png"
MACHINERY = "Manufacture of electrical machinery and apparatus n.e.c."


@pytest.fixture
def page(linked):  # noqa: F811
    from playwright.sync_api import sync_playwright

    client, _ = linked
    sent: list[tuple[str, str, dict | None]] = []

    def forward(route):
        req = route.request
        parts = urlsplit(req.url)
        body = req.post_data
        sent.append((req.method, parts.path, json.loads(body) if body else None))
        res = client.request(req.method, parts.path + (f"?{parts.query}" if parts.query else ""), content=body,
                             headers={"content-type": "application/json"})
        route.fulfill(status=res.status_code, body=res.content, headers={"content-type": res.headers.get("content-type", "application/json")})

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.console_errors = []
        page.on("console", lambda m: m.type == "error" and page.console_errors.append(m.text))
        for pattern in ("**/api/value-chain/**", "**/api/portfolio/portfolios", "**/api/taxonomies"):
            page.route(pattern, forward)
        page.sent = sent
        yield page
        browser.close()


def field(scope, label):
    """A labelled control: a wrapping <label> adds the control's value to its name, so match the label's start."""
    return scope.get_by_label(re.compile(rf"^{re.escape(label)}"))


def holding_row(page, name):
    return page.get_by_role("row").filter(has_text=name)


def open_p(page):
    page.goto(URL + "/#/valueChain/portfolio")
    page.get_by_text("Pick a portfolio.").wait_for()
    field(page, "Portfolio").select_option("P")
    page.get_by_text("Linked 90.0% of NAV · footprint covers 70.0%").wait_for()


def edit(page, name):
    holding_row(page, name).get_by_role("button", name="Edit link").click()
    editor = page.get_by_role("region", name="Link editor")
    editor.get_by_text("Current source:").wait_for()
    return editor


def test_ac38_ac39_coverage_footprint_holdings(page):
    open_p(page)
    assert page.url.endswith("#/valueChain/portfolio/P")
    assert page.get_by_text("2.2 t CO₂e per M EUR invested").is_visible()
    rows = page.get_by_role("region", name="Holdings").get_by_role("row")
    assert [r.inner_text().split("\t")[:3] for r in rows.all()[1:]] == [
        ["Sec cm", "40.0%", "code"], ["Sec sx", "30.0%", "split"], ["Sec nx", "20.0%", "nodes"], ["Cash", "10.0%", "none"]]
    SCREENSHOT.parent.mkdir(exist_ok=True)
    page.screenshot(path=str(SCREENSHOT), full_page=True)
    page.emulate_media(color_scheme="dark")
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth") <= 390  # no sideways scroll on a phone
    page.screenshot(path=str(SCREENSHOT.with_name("value-chain-portfolio-390-dark.png")), full_page=True)
    assert page.console_errors == []


def test_ac40_ac41_ac42_edit_split_then_reset(page):
    open_p(page)
    editor = edit(page, "Sec sx")
    shares = field(editor, "Share %")
    assert shares.count() == 2  # the stored 50/50 split
    editor.get_by_role("button", name="Nodes").click()  # another mode starts from one empty row
    assert (shares.count(), shares.nth(0).input_value()) == (1, "100")
    editor.get_by_role("button", name="Revenue split").click()
    editor.get_by_role("button", name="Reset to default").click()
    holding_row(page, "Sec sx").get_by_role("cell", name="code", exact=True).wait_for()
    editor.get_by_role("button", name="Revenue split").click()
    field(editor, "ICIO code").nth(0).select_option("C27")
    editor.get_by_role("button", name="Add row").click()
    field(editor, "ICIO code").nth(1).select_option("B07")
    shares.nth(0).fill("60")
    shares.nth(1).fill("30")
    editor.get_by_role("button", name="Save").click()
    editor.get_by_text("shares must sum to 1").wait_for()
    shares.nth(1).fill("40")
    editor.get_by_role("button", name="Save").click()
    holding_row(page, "Sec sx").get_by_text(f"CN · {MACHINERY} 60.0%").wait_for()
    puts = [b for m, _, b in page.sent if m == "PUT"]
    assert [p["share"] for p in puts[-1]["parts"]] == [0.6, 0.4]

    editor.get_by_role("button", name="Reset to default").click()
    holding_row(page, "Sec sx").get_by_role("cell", name="code", exact=True).wait_for()
    assert any(m == "DELETE" and path.endswith("/links/company/sx") for m, path, _ in page.sent)


def test_ac43_ac43b_activity_line_and_its_link(page):
    open_p(page)
    field(page, "Taxonomy").select_option("T")
    page.get_by_role("combobox", name=re.compile(r"^Activity")).select_option("a1")
    page.get_by_text("Copper and nickel mining: 35.0% of NAV directly · 51.9% of upstream").wait_for()
    page.get_by_role("region", name="Activity").get_by_role("button", name="Edit link").click()
    editor = page.get_by_role("region", name="Link editor")
    editor.get_by_role("button", name="Nodes").click()
    field(editor, "Node").fill("copper")
    editor.get_by_role("button", name="Mining of copper ores and concentrates · CN").click()
    editor.get_by_role("button", name="Save").click()
    page.get_by_text("Copper and nickel mining: 10.7% of NAV directly · 25.5% of upstream").wait_for()
    assert page.console_errors == []


def test_ac44_shocks_view_portfolio_lens(page):
    page.goto(URL + "/#/valueChain/CN.4/shock")
    page.get_by_role("group", name="Target").get_by_role("button", name="All of CN").click()
    field(page, "Change (%)").fill("-10")
    field(page, "Portfolio").select_option("P")
    page.get_by_text("Portfolio output change −8.23%").wait_for()
    SCREENSHOT.parent.mkdir(exist_ok=True)
    page.screenshot(path=str(SCREENSHOT.with_name("value-chain-shock-lens.png")), full_page=True)
    assert page.url.endswith("#/valueChain/CN.4/shock/P")  # a reload or a shared link keeps the lens
    page.reload()
    page.get_by_role("group", name="Target").get_by_role("button", name="All of CN").click()
    page.get_by_text("Portfolio output change −8.23%").wait_for()
    page.get_by_role("group", name="Model").get_by_role("button", name="Carbon price").click()
    page.get_by_text("Portfolio price change 0.03%").wait_for()
    field(page, "Portfolio").select_option("")
    page.get_by_role("heading", name="Price change").wait_for()
    assert page.get_by_text("Portfolio price change").count() == 0
    assert page.console_errors == []


def test_shocks_view_url_portfolio_stale_link_and_tab(page):
    # a stale or mistyped portfolio in the URL shows its 404 and can be cleared with None
    page.goto(URL + "/#/valueChain/CN.4/shock/OLD")
    page.get_by_text("unknown portfolio 'OLD'").wait_for()
    assert field(page, "Portfolio").input_value() == "OLD"
    field(page, "Portfolio").select_option("")
    page.get_by_role("heading", name="Output change").wait_for()
    assert page.url.endswith("#/valueChain/CN.4/shock") and page.get_by_text("unknown portfolio").count() == 0
    # after picking P, the Shocks tab links back to the lens instead of dropping it
    field(page, "Portfolio").select_option("P")
    page.get_by_text("Portfolio output change").wait_for()
    tab = page.get_by_role("navigation", name="Views").get_by_role("link", name="Shocks")
    assert tab.get_attribute("href").endswith("#/valueChain/CN.4/shock/P")
    tab.click()
    assert page.url.endswith("#/valueChain/CN.4/shock/P")
    page.reload()
    page.get_by_text("Portfolio output change").wait_for()
    # the one 404 is the stale link's, provoked above
    assert [e for e in page.console_errors if "status of 404" not in e] == []
