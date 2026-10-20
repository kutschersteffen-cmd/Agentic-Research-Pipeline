"""Company page Transition section (transition-plan-alignment spec AC-51, AC-44, AC-53..AC-55) against the running app.

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
SCREENSHOT_P2 = SCREENSHOT.with_name("transition-section-p2.png")
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
EU, US, CN = "European Union", "United States", "China"
TP = "Fixture Steel Transition Plan 2025 p."


def bvalue(vid, fact, value, unit, shown, document, document_id, page, quote):
    return {"id": vid, "url": None, "fact": fact, "page": page, "unit": unit, "quote": quote, "shown": shown, "value": value,
            "reason": None, "counted": True, "locator": None, "document": document, "extracted": shown, "confidence": "high",
            "entered_by": "b.approver", "document_id": document_id, "machine_checked": True}


def b02(b, c, d):
    return {k: {"met": met, "text": text} for k, (met, text) in zip("bcd", (b, c, d), strict=True)}


def hand_rated(region, evidence):
    return {"code": "STL-R1", "region": region, "rating": "L", "basis": "hand_rated", "evidence": evidence, "values": []}


NO_FUNDS, NO_SAVING = (False, "No funding stated"), (False, "No quantified GHG saving")
C_PHASE2 = {  # C's phase 2 keys as tests/db/test_transition_alignment_api.py serves them with F-TA ratified
    "regions": [EU, US, CN],
    "actions": [
        {"key": "action:P1:12:1", "action_id": "steel.h2_dri", "act_lever": None,
         "text": "We will commission a 2 Mt hydrogen-based DRI plant in Sweden by 2028.", "status": "planned", "year": 2028,
         "region": EU, "citation": TP + "12", "timeframe": "near term (2028)",
         "b02": b02((True, "near term (2028)"), (True, "3.5 MtCO2e/yr"),
                    (True, "1500 EUR million needed, 600 EUR million allocated")),
         "barriers": [
             {"code": "STL-R1", "region": EU, "rating": "H", "basis": "derived",
              "evidence": "H: Effective carbon price >= 50 USD/tCO2 and Border levy in force is Yes. Effective carbon price = "
                          "72 USD/tCO2 (EU ETS Market Report 2026, p. 12): pass. Border levy in force = Yes "
                          "(CBAM Regulation 2023/956, p. 3): pass.",
              "values": [
                  bvalue("1", "price", 72.0, "USD/tCO2", "72 USD/tCO2", "EU ETS Market Report 2026", 1, 12,
                         "The effective carbon price was USD 72/tCO2."),
                  bvalue("2", "applies", True, None, "Yes", "EU ETS Market Report 2026", 2, 4,
                         "The carbon price applies to steel producers."),
                  bvalue("3", "levy", True, None, "Yes", "CBAM Regulation 2023/956", 3, 3,
                         "The border levy applies from 1 January 2026."),
              ]},
             {"code": "STL-T1", "region": EU, "rating": "M", "basis": "derived",
              "evidence": "H: Renewable hydrogen cost <= 2 USD/kg H2. Renewable hydrogen cost = 6 USD/kg H2 (Hydrogen Cost "
                          "Review 2026, p. 7): fail. M: Renewable hydrogen cost <= 7 USD/kg H2. Renewable hydrogen cost = "
                          "6 USD/kg H2 (Hydrogen Cost Review 2026, p. 7): pass.",
              "values": [bvalue("4", "h2_cost", 6.0, "USD/kg H2", "6 USD/kg H2", "Hydrogen Cost Review 2026", 4, 7,
                                "Renewable hydrogen cost was USD 6/kg H2.")]},
         ],
         "note": None, "fact_ids": [49, 50, 51, 52, 53, 54, 55, 56]},
        {"key": "action:P1:15:1", "action_id": "steel.scrap_eaf",
         "act_lever": {"wording": "More scrap, process efficiency, zero-GHG power", "citation": "ACT Core methodology p.110"},
         "text": "Our electric arc furnace in Ohio has run on scrap since 2022.", "status": "implemented", "year": 2022,
         "region": US, "citation": TP + "15", "timeframe": "implemented (2022)",
         "b02": b02((True, "implemented (2022)"), NO_SAVING, NO_FUNDS),
         "barriers": [hand_rated(US, "No federal carbon price applies to steel.")], "note": None,
         "fact_ids": [62, 63, 64, 65, 66]},
        {"key": "action:P1:16:1", "action_id": "steel.ccus", "act_lever": None,
         "text": "We are studying carbon capture at our Tianjin plant.", "status": "planned", "year": None, "region": CN,
         "citation": TP + "16", "timeframe": None, "b02": b02((False, "No timeframe: ignored"), NO_SAVING, NO_FUNDS),
         "barriers": [hand_rated(CN, "National ETS price too low to matter.")], "note": None, "fact_ids": [71, 72, 73, 74]},
    ],
    "b02a": {"met": False, "text": "not met: 1 implemented, 1 planned with a timeframe (needs 3 and 1)"},
    "assumptions": [
        {"kind": "carbon_price", "region": EU, "year": 2030, "citation": TP + "20", "fact_id": 38, "comparisons": [
            {"code": "STL-R1", "region": EU, "assumption": "97.2 USD/tCO2 (90 EUR/tCO2)",
             "evidence": "72 USD/tCO2 (EU ETS Market Report 2026, p. 12)", "gap": "+25.2 USD/tCO2", "reason": None}]},
        {"kind": "h2_cost", "region": None, "year": None, "citation": TP + "21", "fact_id": 40, "comparisons": [
            {"code": "STL-T1", "region": EU, "assumption": "3 USD/kg H2",
             "evidence": "6 USD/kg H2 (Hydrogen Cost Review 2026, p. 7)", "gap": "-3 USD/kg H2", "reason": None}]},
    ],
}
C_TRANSITION = {
    "in_scope": True, "reason": None, "sector": "Steel", "benchmarks_version": 3, "rule_book_version": 7, **C_PHASE2,
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


def test_ac53_ac55_c_shows_plan_actions_and_assumptions(page):
    section = open_company(page, "C", company("C", "Fixture Steel AG", "2410"), [FACT], C_TRANSITION)
    dri = section.get_by_role("article", name="We will commission a 2 Mt hydrogen-based DRI plant in Sweden by 2028.")
    dri.wait_for()
    rows = dri.get_by_role("row")
    assert [r.inner_text().split("\t")[:3] for r in rows.all()[1:]] == [[EU, "STL-R1", "H"], [EU, "STL-T1", "M"]]  # AC-53
    assert dri.get_by_text("1500 EUR million needed, 600 EUR million allocated", exact=True).is_visible()  # AC-54
    carbon = section.get_by_role("row").filter(has_text="97.2 USD/tCO2 (90 EUR/tCO2)")
    assert carbon.get_by_role("cell").last.inner_text() == "+25.2 USD/tCO2"  # AC-55
    assert dri.get_by_role("link", name="72 USD/tCO2 (EU ETS Market Report 2026, p. 12)").get_attribute("href").endswith(
        "/api/transition-barrier/documents/1#page=12")  # AC-43: the figure opens its barrier citation
    SCREENSHOT_P2.parent.mkdir(exist_ok=True)
    page.screenshot(path=str(SCREENSHOT_P2), full_page=True)


def test_ac44_q_is_not_in_scope(page):
    section = open_company(page, "Q", company("Q", "Fixture Foods SA", "1050"), [], Q_TRANSITION)
    section.get_by_text("Not in scope: ISIC 1050 is not in a transition-barrier sector", exact=True).wait_for()
    assert section.get_by_role("button").count() == 0
