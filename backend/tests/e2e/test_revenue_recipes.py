"""Recipe form of the revenue-routes spec against the running app; value-chain calls go to an in-process API on fixture F."""

import os
import re
from urllib.parse import urlsplit

import pytest

from arp.config import Settings
from tests.test_revenue_routes import BASE, R, builds, client, env  # noqa: F401  (fixtures)

URL = os.environ.get("ARP_E2E_URL")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]


@pytest.fixture
def page(client):  # noqa: F811
    from playwright.sync_api import sync_playwright

    def forward(route):
        req = route.request
        parts = urlsplit(req.url)
        res = client.request(req.method, parts.path + (f"?{parts.query}" if parts.query else ""), content=req.post_data,
                             headers={"content-type": "application/json"})
        route.fulfill(status=res.status_code, body=res.content, headers={"content-type": res.headers.get("content-type", "application/json")})

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page()
        page.route("**/api/value-chain/**", forward)
        yield page
        browser.close()


def test_switching_recipes_reloads_the_form(page, client):  # noqa: F811
    """Going from recipe A to B without leaving the form shows B, so Save can never write A's fields onto B."""
    a = client.post(f"{BASE}/recipes", json={**R, "name": "Recipe A"}).json()["recipe_id"]
    b = client.post(f"{BASE}/recipes", json={**R, "name": "Recipe B", "output_meur": 40}).json()["recipe_id"]
    name = page.get_by_label(re.compile("^Name"))
    page.goto(f"{URL}/#/valueChain/recipes/{a}")
    page.get_by_role("heading", name="Recipe A").wait_for()
    assert name.input_value() == "Recipe A"
    page.evaluate(f"window.location.hash = '#/valueChain/recipes/{b}'")
    page.get_by_role("heading", name="Recipe B").wait_for()
    assert (name.input_value(), page.get_by_label(re.compile("^Output")).input_value()) == ("Recipe B", "40")
