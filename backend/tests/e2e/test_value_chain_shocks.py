"""Shocks view (#/valueChain/<id>/shock) against the running app, with the value-chain API stubbed
(the e2e stack has no EXIOBASE build); spec value-chain-shocks Appendix C."""

import os
from urllib.parse import parse_qs, urlparse

import pytest

from arp.api.routers.value_chain import MODEL_CAVEATS
from arp.config import Settings

URL = os.environ.get("ARP_E2E_URL")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]
CAVEAT = "EXIOBASE 3.11.2 · 2022 · basic prices, M EUR"
NODE = {
    "node_id": "CN.2", "region": "CN", "region_label": "CN", "sector": "Mining of copper ores and concentrates",
    "edition": "e", "caveat": CAVEAT, "output_meur": 100, "ghg_t_per_meur": 1, "energy_tj_per_meur": 0,
    "jobs_per_meur": 0, "va_share": 0.5, "suppliers": [], "customers": [],
}
GROUPS = [[f"G{i}", -1.0 * i] for i in range(1, 7)]


def _quantity(model):
    return {
        "edition": "e", "caveat": CAVEAT, "model_caveat": MODEL_CAVEATS[model], "model": model, "unit": "pct",
        "change_pct": -10, "total_meur": -30.1819, "by_region": GROUPS, "by_sector": GROUPS,
        "nodes": [{"node_id": "CN.2", "region_label": "CN", "sector": NODE["sector"], "delta_meur": -1.5}],
        "shocked": [{"node_id": "CN.2", "base_meur": 70, "shock_meur": -7}], "skipped": [],
        "indicators": {"ghg": -45.7955, "energy": -0.8992, "jobs": -299.17}, "focus": {"node_id": "CN.2", "delta_meur": -1.5},
    }


PRICE = {
    "edition": "e", "caveat": CAVEAT, "model_caveat": MODEL_CAVEATS["price"], "carbon_eur_per_t": 100,
    "covered_regions": ["CN", "DE"], "priced_t": 627, "carbon_cost_meur": 0.0627, "by_region": GROUPS,
    "by_sector": GROUPS, "nodes": [], "focus": {"node_id": "CN.2", "dp_pct": 0.0148},
}


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(10_000)
        page.console_errors = []
        page.on("console", lambda m: m.type == "error" and page.console_errors.append(m.text))
        page.shock_requests = []

        def quantity(route):
            page.shock_requests.append(route.request.url)
            route.fulfill(json=_quantity(parse_qs(urlparse(route.request.url).query)["model"][0]))

        def price(route):
            page.shock_requests.append(route.request.url)
            route.fulfill(json=PRICE)

        page.route("**/api/value-chain/nodes/CN.2?*", lambda route: route.fulfill(json=NODE))
        page.route("**/api/value-chain/shock/quantity?*", quantity)
        page.route("**/api/value-chain/shock/price?*", price)
        yield page
        browser.close()


def _last_query(page):
    return parse_qs(urlparse(page.shock_requests[-1]).query)


def test_shocks_view(page):  # AC-26 to AC-30e, on stubbed numbers
    page.goto(URL + "/#/valueChain/CN.2/shock")
    page.get_by_text("Δ output −30.2\u00a0M\u00a0EUR").wait_for()
    assert page.get_by_role("button", name="Demand").get_attribute("aria-pressed") == "true"
    assert page.get_by_role("button", name="This node").get_attribute("aria-pressed") == "true"
    assert page.get_by_label("Change (%)").input_value() == "-10"
    assert _last_query(page) == {
        "model": ["demand"], "change": ["-10"], "unit": ["pct"], "node": ["CN.2"], "top": ["6"], "focus": ["CN.2"],
    }
    assert page.get_by_text(MODEL_CAVEATS["demand"]).is_visible()
    assert page.get_by_role("heading", name="Output change").is_visible()
    assert page.get_by_text("−45.8 t CO₂e").is_visible()
    assert page.get_by_text(CAVEAT).is_visible()

    page.get_by_role("button", name="All of CN").click()
    page.wait_for_load_state("networkidle")
    assert _last_query(page)["region"] == ["CN"] and "node" not in _last_query(page)

    page.get_by_role("button", name="Supply dependency").click()
    page.get_by_role("heading", name="Dependency indicator: output change").wait_for()
    assert page.get_by_text(MODEL_CAVEATS["supply"]).is_visible()
    headings = " ".join(page.locator("h1, h2, .field-label, button").all_inner_texts())
    assert "forecast" not in headings.lower()

    page.get_by_role("button", name="Carbon price").click()
    page.get_by_text("this node 0.01%").wait_for()
    assert _last_query(page) == {"carbon_eur_per_t": ["100"], "top": ["6"], "focus": ["CN.2"]}
    assert page.get_by_role("region", name="By region").locator("li").count() == 6
    page.get_by_role("button", name="EU-27").click()
    page.wait_for_load_state("networkidle")
    assert len(_last_query(page)["region"]) == 27 and "GB" not in _last_query(page)["region"]
    page.get_by_role("button", name="CN only").click()
    page.wait_for_load_state("networkidle")
    assert _last_query(page)["region"] == ["CN"]
    assert page.console_errors == []

    for view in ("", "/tree", "/footprint"):  # AC-30: each view links to the Shocks view of the same node
        page.goto(URL + "/#/valueChain/CN.2" + view)
        assert page.get_by_role("link", name="Shocks").get_attribute("href") == "#/valueChain/CN.2/shock"
