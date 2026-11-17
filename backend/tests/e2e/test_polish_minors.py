"""Deferred polish minors (UI polish 2, top bar PR 2) against the running app."""

import pytest
from playwright.sync_api import expect

from tests.e2e.test_top_bar_pr2 import _runs_stub
from tests.e2e.test_ui_polish_2 import URL, _open, _probe, _style, page  # noqa: F401  (page is a fixture)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]


def test_selected_phone_card_tints_whole(page):  # noqa: F811
    _runs_stub(page, [{"run_id": "e2e-vote-pick", "run_type": "proxy_voting", "status": "completed", "review_count": 0, "company_count": 3, "completed_count": 3}], "**/api/runs*")
    _open(page, "/#/voting", 390, 844)
    row = page.locator("table.stack-on-phone tbody tr", has_text="e2e-vote-pick").first
    row.click()
    page.wait_for_function("() => document.querySelector('table.stack-on-phone tr[aria-current]')")
    picked = page.locator("table.stack-on-phone tr[aria-current]").first
    tint = _probe(page, "--accent-tint", "backgroundColor")
    expect(picked).to_have_css("background-color", tint)  # retries: the row's background has a colour transition
    for td in picked.locator("td").all():
        assert _style(td, "backgroundColor") == "rgba(0, 0, 0, 0)"
