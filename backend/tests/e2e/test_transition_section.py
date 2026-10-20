"""Company page Transition section (transition-plan-alignment spec AC-51, AC-44) against the running app.

The company, its facts and its transition check are stubbed with Playwright routing: C's and Q's
responses as tests/db/test_transition_alignment_api.py serves them over the seeded fixtures.
"""

import os
from pathlib import Path

import pytest

from arp.config import Settings
from arp.schemas.transition_alignment import TransitionOut

URL = os.environ.get("ARP_E2E_URL")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

SCREENSHOT = Path(__file__).resolve().parents[2] / "test-results" / "transition-section.png"
AR = "Fixture Steel Annual Report 2025 p."


def company(cid, name, isic):
    return {"id": cid, "name": name, "country": None, "sector": None, "isic_code": isic, "fiscal_year_end": "12-31",
            "regimes": [], "identifiers": [{"scheme": "UNIVERSE", "value": cid, "valid_from": "2026-10-20", "valid_to": None}],
            "fact_counts": {"approved": 14}, "open_review_items": 0, "documents": 2, "runs": 0, "holders": [],
            "holders_available": True}


def amount(field_id, year, shown, fact_id, citation):
    return {"field_id": field_id, "year": year, "shown": shown, "fact_id": fact_id, "citation": citation}


FACT = {"fact_id": 18, "field_id": "tc_lowcarbon_capex_share_pct", "kind": "extracted", "period_end": "2025-12-31", "basis": "",
        "value": 12, "canonical_value": None, "canonical_unit": None, "unit": "%", "status": "approved",
        "source_kind": "extraction", "source_label": AR + "45", "licence": None, "conflicting_sources": False,
        "valid_from": "2026-10-20T00:31:47Z", "valid_to": None}
PHASE2 = {"regions": [], "actions": [], "b02a": None, "assumptions": []}
C_TRANSITION = {
    "in_scope": True, "reason": None, "sector": "Steel", "benchmarks_version": 3, "rule_book_version": 7, **PHASE2,
    "capex": {
        "reporting_year": 2025,
        "share_ry": {"value": 12.0, "source": "disclosed", "fact_ids": [18]},
        "share_ry1": {"value": 20.0, "source": "disclosed", "fact_ids": [29]},
        "share_used": 20.0, "share_used_shown": "20", "rule": "RY+1 higher: RY+1 used",
        "benchmark": {"value": 80.0, "unit": "%", "method": "ACT Core D01.a, generic row", "citation": "ACT Core methodology p.62",
                      "url": None, "licence": "ACT methodology, internal non-commercial use with citation."},
        "ratio": 0.25, "ratio_shown": "0.25", "not_scored": None,
        "headline": "Low-carbon capex 20% vs benchmark 80%: 0.25",
        "amounts": [
            amount("tc_capex_total", 2025, "1000 EUR million", 16, AR + "44"),
            amount("tc_lowcarbon_capex", 2025, "120 EUR million", 17, AR + "45"),
            amount("tc_capex_total_planned", 2026, "1100 EUR million", 28, "Fixture Steel Transition Plan 2025 p.18"),
            amount("tc_carbon_intensive_capex", 2025, "300 EUR million", 19, AR + "46"),
            amount("tc_rnd_total", 2024, "40 EUR million", 25, AR + "51"),
            amount("tc_rnd_total", 2025, "50 EUR million", 22, AR + "50"),
            amount("tc_lowcarbon_rnd", 2024, "20 EUR million", 26, AR + "51"),
            amount("tc_lowcarbon_rnd", 2025, "30 EUR million", 23, AR + "50"),
            amount("tc_lowcarbon_rnd_early", 2024, "12 EUR million", 27, AR + "51"),
            amount("tc_lowcarbon_rnd_early", 2025, "15 EUR million", 24, AR + "50"),
        ],
        "rnd_tests": [
            {"id": "lc_share", "label": "Low-carbon share of R&D", "used": 60.0, "rule": "RY higher: RY used", "benchmark": 80.0,
             "ratio": 0.75, "ratio_shown": "0.75", "not_scored": None, "fact_ids": [26, 25, 23, 22]},
            {"id": "early_stage", "label": "Early-stage share of low-carbon R&D", "used": 55.0,
             "rule": "RY lower: average of RY-1 and RY", "benchmark": 65.0, "ratio": 0.8461538461538461, "ratio_shown": "0.85",
             "not_scored": None, "fact_ids": [27, 26, 24, 23]},
        ],
        "redlines": [
            {"id": "stl_bf", "label": "No new blast furnace without CCS or a near-zero route", "status": "not breached",
             "text": "No new blast furnace without CCS or a near-zero route", "citation": AR + "48", "fact_id": 21,
             "source": "owner-defined (2026-10-19)"},
        ],
        "licence_note": "Internal, non-commercial use, with citation (owner decision 2026-10-19).",
    },
}
Q_TRANSITION = {"in_scope": False, "reason": "ISIC 1050 is not in a transition-barrier sector", "sector": None,
                "benchmarks_version": 3, "rule_book_version": 7, "capex": None, **PHASE2}
for _fixture in (C_TRANSITION, Q_TRANSITION):  # the stubs cannot drift from the served model
    TransitionOut.model_validate(_fixture)


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(10_000)
        yield page
        browser.close()


def open_company(page, ref, summary, facts, transition):
    page.route(f"**/api/companies/{ref}", lambda r: r.fulfill(json=summary))
    page.route(f"**/api/companies/{ref}/facts*", lambda r: r.fulfill(json=facts))
    page.route(f"**/api/companies/{ref}/transition", lambda r: r.fulfill(json=transition))
    page.goto(f"{URL}/#/companies/{ref}")
    return page.get_by_role("region", name="Transition")


def test_ac51_c_shows_the_capex_headline(page):
    section = open_company(page, "C", company("C", "Fixture Steel AG", "2410"), [FACT], C_TRANSITION)
    section.get_by_text("Low-carbon capex 20% vs benchmark 80%: 0.25", exact=True).wait_for()
    assert section.get_by_role("button", name="12%").is_visible()
    SCREENSHOT.parent.mkdir(exist_ok=True)
    page.screenshot(path=str(SCREENSHOT), full_page=True)


def test_ac44_q_is_not_in_scope(page):
    section = open_company(page, "Q", company("Q", "Fixture Foods SA", "1050"), [], Q_TRANSITION)
    section.get_by_text("Not in scope: ISIC 1050 is not in a transition-barrier sector", exact=True).wait_for()
    assert section.get_by_role("button").count() == 0
