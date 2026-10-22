"""Company page Transition section (transition-plan-alignment spec AC-51, AC-44, AC-53..AC-55; plan-delivery-checks
spec AC-89, AC-112, AC-119, AC-121, AC-126..AC-128; delivery-KPIs spec AC-187..AC-191, AC-200..AC-203) against the running app.

The company, its facts and its transition check are stubbed with Playwright routing: C's and Q's
responses as tests/db/test_transition_alignment_api.py serves them over the seeded fixtures.
"""

import json
import os
import shutil
from pathlib import Path

import pytest

from arp.config import Settings, get_settings
from arp.db.company_view import FactTrail
from arp.schemas.transition_alignment import TransitionOut
from arp.transition_barrier import dataset
from arp.transition_barrier.rule_book import compute_fingerprint, load_rule_book
from arp.transition_barrier.validation import read_and_validate
from tests.transition_alignment_helpers import FIXTURES

URL = os.environ.get("ARP_E2E_URL")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

SCREENSHOT = Path(__file__).resolve().parents[2] / "test-results" / "transition-section.png"
SCREENSHOT_P2 = SCREENSHOT.with_name("transition-section-p2.png")
SCREENSHOT_DC = SCREENSHOT.with_name("transition-section-dc.png")
SCREENSHOT_FLAGS = SCREENSHOT.with_name("transition-section-flags.png")
SCREENSHOTS = {v: SCREENSHOT.with_name(f"delivery-kpis-{v}.png") for v in ("k", "x", "c", "h-390")}
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
    return {k: {"met": met, "text": text, "fact_ids": ids} for k, (met, text, ids) in zip("bcd", (b, c, d), strict=True)}


def hand_rated(region, evidence):
    return {"code": "STL-R1", "region": region, "rating": "L", "basis": "hand_rated", "evidence": evidence, "values": []}


NO_FUNDS, NO_SAVING = (False, "No funding stated", []), (False, "No quantified GHG saving", [])
C_PHASE2 = {  # C's phase 2 keys as tests/db/test_transition_alignment_api.py serves them with F-TA ratified
    "regions": [EU, US, CN],
    "actions": [
        {"key": "action:P1:12:1", "action_id": "steel.h2_dri", "act_lever": None,
         "text": "We will commission a 2 Mt hydrogen-based DRI plant in Sweden by 2028.", "status": "planned", "year": 2028,
         "region": EU, "citation": TP + "12", "timeframe": "near term (2028)",
         "b02": b02((True, "near term (2028)", [51, 52]), (True, "3.5 MtCO2e/yr", [56]),
                    (True, "1500 EUR million needed, 600 EUR million allocated", [54, 55])),
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
         "b02": b02((True, "implemented (2022)", [64, 65]), NO_SAVING, NO_FUNDS),
         "barriers": [hand_rated(US, "No federal carbon price applies to steel.")], "note": None,
         "fact_ids": [62, 63, 64, 65, 66]},
        {"key": "action:P1:16:1", "action_id": "steel.ccus", "act_lever": None,
         "text": "We are studying carbon capture at our Tianjin plant.", "status": "planned", "year": None, "region": CN,
         "citation": TP + "16", "timeframe": None, "b02": b02((False, "No timeframe: ignored", [73]), NO_SAVING, NO_FUNDS),
         "barriers": [hand_rated(CN, "National ETS price too low to matter.")], "note": None, "fact_ids": [71, 72, 73, 74]},
    ],
    "b02a": {"met": False, "text": "not met: 1 implemented, 1 planned with a timeframe (needs 3 and 1)", "fact_ids": []},
    "assumptions": [
        {"kind": "carbon_price", "region": EU, "year": 2030, "citation": TP + "20", "fact_id": 38, "comparisons": [
            {"code": "STL-R1", "region": EU, "assumption": "97.2 USD/tCO2 (90 EUR/tCO2)",
             "evidence": "72 USD/tCO2 (EU ETS Market Report 2026, p. 12)", "gap": "+25.2 USD/tCO2", "reason": None}],
         "scenario": [{"region": EU, "year": 2030, "scenario": "140 USD/tCO2 (IEA NZE 2030, advanced economies)",  # BM-S
                       "assumption": "97.2 USD/tCO2 (90 EUR/tCO2)", "gap": "-42.8 USD/tCO2", "reason": None}]},
        {"kind": "h2_cost", "region": None, "year": None, "citation": TP + "21", "fact_id": 40, "comparisons": [
            {"code": "STL-T1", "region": EU, "assumption": "3 USD/kg H2",
             "evidence": "6 USD/kg H2 (Hydrogen Cost Review 2026, p. 7)", "gap": "-3 USD/kg H2", "reason": None}],
         "scenario": []},
    ],
}
def target(key, pct, year, kind, score, page, fact_ids):
    return {"key": key, "scope": "S1+2", "pct": pct, "year": year, "base_year": 2019, "base_emissions_shown": "20 MtCO2e",
            "kind": kind, "ratio": "0.75", "score": score, "reason": None, "citation": TP + page, "fact_ids": fact_ids}


COVERAGE_TEXT = "Listed actions cover 58.33% of the 2030 target gap (3.5 of 6 MtCO2e/yr)"
C_DELIVERY = {  # C's delivery-check keys as tests/db/test_transition_alignment_api.py serves them with BM-S
    "targets": [target("target:P1:22:1", 30.0, 2030, "running", 75.0, "22", [89, 90, 91, 92, 93, 94]),
                target("target:P1:23:1", 10.0, 2023, "past", 50.0, "23", [101, 102, 103, 104, 105, 106])],
    "target_progress": {"score": 68.75, "text": "Target progress 68.75% (ACT GE 1.4)"},
    "coverage": {"target_key": "target:P1:22:1", "percent": 58.33, "text": COVERAGE_TEXT, "reason": None, "actions": [
        {"key": "action:P1:12:1", "saving_shown": "3.5 MtCO2e/yr", "summed": True, "reason": None},
        {"key": "action:P1:15:1", "saving_shown": None, "summed": False, "reason": "No quantified saving"},
        {"key": "action:P1:16:1", "saving_shown": None, "summed": False, "reason": "No quantified saving"}]},
    "phaseouts": [{"key": "phaseout:P1:24:1", "activity": "blast furnace steelmaking", "share": 50.0, "year": 2035,
                   "method": "closure", "share_points": 25, "date_points": 75, "score": 40.0, "reason": None,
                   "timeline_text": "No ACT Core sector timeline", "note": None, "citation": TP + "24",
                   "fact_ids": [111, 112, 113, 114]}],
}
def flag(fid, title, state, text, cite, fact_ids=()):
    return {"id": fid, "title": title, "state": state, "text": text, "cite": cite, "fact_ids": list(fact_ids)}


OFFSETS_FACT = 61  # P1 p.26
FLAG_TITLES = ("Falling emissions claimed, no low-carbon capex", "Net zero without phase-out", "Expansion against net zero",
               "Regions left out", "Offsets emphasised")
C_FLAGS = [  # C's flags with the defaults (titles, texts and cites as the spec; fact ids are stub values)
    flag("no_lowcarbon_capex", FLAG_TITLES[0], "clear", "No flag.", "ACT Framework p.64", [89, 90, 91, 92, 93, 94]),
    flag("net_zero_no_phaseout", FLAG_TITLES[1], "clear", "No flag.", "ACT Framework pp.61–62", [60]),
    flag("expansion_vs_net_zero", FLAG_TITLES[2], "clear", "No flag.", "ACT Framework p.62", [60]),
    flag("regions_left_out", FLAG_TITLES[3], "clear", "No flag.", "ACT Framework p.61", [3, 4, 5]),
    flag("offsets_emphasised", FLAG_TITLES[4], "raised", "Does not state that credits are used only for residual emissions.",
         "ACT Framework p.62; ACT Core p.26", [OFFSETS_FACT]),
]
C_HEADER = "Consistency: 1 of 5 checks raise a flag"
C_TRANSITION = {
    "in_scope": True, "reason": None, "sector": "Steel", "benchmarks_version": 4, "rule_book_version": 7, **C_PHASE2, **C_DELIVERY,
    "flags": C_FLAGS, "flags_header": C_HEADER,
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
    "delivery_kpis": [], "delivery_kpis_note": "No delivery KPI for this sector.",  # AC-175
}
Q_TRANSITION = {"in_scope": False, "reason": "ISIC 1050 is not in a transition-barrier sector", "sector": None,
                "benchmarks_version": 3, "rule_book_version": 7, "capex": None, **PHASE2}
C_NO_PHASEOUT = {**C_TRANSITION, "phaseouts": []}
C_NO_NET_ZERO = {**C_TRANSITION, "flags": [
    flag("net_zero_no_phaseout", FLAG_TITLES[1], "not checked", "No net-zero answer", "ACT Framework pp.61–62") if f["id"] == "net_zero_no_phaseout"
    else flag("expansion_vs_net_zero", FLAG_TITLES[2], "not checked", "No net-zero answer", "ACT Framework p.62") if f["id"] == "expansion_vs_net_zero"
    else f for f in C_FLAGS]}
C_OFFSETS_CLEAR = {**C_TRANSITION, "flags_header": "Consistency: no check raises a flag", "flags": [
    {**f, "state": "clear", "text": "No flag."} if f["id"] == "offsets_emphasised" else f for f in C_FLAGS]}


# --- delivery KPIs: K, X and H as tests/db/test_transition_alignment_api.py serves them (K, X, H facts; K1) ---------

def kpi(kid, label, field, cite, value, fact_id, range_text, position, action_keys=()):
    return {"id": kid, "label": label, "field_id": field, "cite": cite, "value": value, "year": 2025 if value is not None else None,
            "fact_ids": [fact_id] if fact_id else [], "range_text": range_text, "position_pct": position, "action_keys": list(action_keys)}


def no_capex(benchmark, method, rnd_tests=()):
    return {"reporting_year": None, "share_ry": None, "share_ry1": None, "share_used": None, "share_used_shown": None, "rule": None,
            "benchmark": {"value": benchmark, "unit": "%", "method": method, "citation": "ACT Core methodology p.62", "url": None,
                          "licence": "ACT methodology, internal non-commercial use with citation."},
            "ratio": None, "ratio_shown": None, "not_scored": "No reporting-year low-carbon capex share",
            "headline": "Capex not scored: No reporting-year low-carbon capex share", "amounts": [], "rnd_tests": list(rnd_tests),
            "redlines": [], "licence_note": "Internal, non-commercial use, with citation (owner decision 2026-10-19)."}


def in_scope(sector, capex, kpis, **extra):
    """An in-scope response with the served defaults filled in (no targets, phase-outs or flags)."""
    return TransitionOut.model_validate({
        "in_scope": True, "reason": None, "sector": sector, "benchmarks_version": 3, "rule_book_version": 7, **PHASE2,
        "capex": capex, "delivery_kpis": kpis, **extra}).model_dump(mode="json")


K_FACT, K1_KEY, K_DOC = 120, "action:P8:9:1", "Fixture Cement Report 2025"
K_KPI = kpi("alt_fuel_share", "Alternative-fuel share of kiln heat", "tc_alt_fuel_share_pct", "ACT Cement v2.0, CEM 2.4a, p.50",
            14.0, K_FACT, "0% → 30%", 46.7, [K1_KEY])
CH = "ACT Chemicals, CH 4.3, p.77"
X_TRANSITION = in_scope("Chemicals", no_capex(77.0, "ACT Core D01.a, oil and gas and chemicals row"), [
    kpi("nh3_electrolytic", "Electrolytic share of ammonia", "tc_nh3_electrolytic_pct", CH, 3.0, 121, "0% → 50%", 6.0),
    kpi("meoh_electrolytic", "Electrolytic share of methanol", "tc_meoh_electrolytic_pct", CH, None, None, "0% → 75%", None),
    kpi("electrolysis_lc_power", "Low-carbon power share of electrolysis", "tc_electrolysis_lc_power_pct", CH, 80.0, 122,
        "0% → 90%", 88.9)])
H_TRANSITION = in_scope("Heavy-Duty Road Transport", no_capex(80.0, "ACT Core D01.a, automotive row"), [
    kpi("zev_sales_share", "Zero-emission share of truck sales", "tc_zev_sales_share_pct", "IEA Net Zero Roadmap 2023, p.93", 4.0,
        124, "0% → 37% (2030) → 65% (2035) → 100% (2050)", 4.0)])
K_TRAIL = {"fact_id": K_FACT, "company_id": "573359bf-ad4f-459c-b47b-b6850829cbfc", "field_id": "tc_alt_fuel_share_pct",
           "period_end": "2025-12-31", "basis": "", "versions": [{
               "fact_id": K_FACT, "status": "approved", "value": 14, "valid_from": "2026-10-22T07:09:20Z", "valid_to": None,
               "superseded_by": None, "load": None, "decisions": [],
               "observation": {"id": 60, "source_kind": "extraction", "run_id": "seed", "value": 14, "value_state": "found",
                               "unit": "%", "confidence": None, "route": "review", "created_at": "2026-10-22T07:09:19Z"},
               "citations": [{"doc_id": "P8", "title": K_DOC, "page": 12, "role": "primary", "grounded": False,
                              "quote": "Alternative fuels supplied 14% of kiln heat in 2025.", "char_start": None, "char_end": None,
                              "passage_id": None, "company_id": "k", "doc_type": "transition_plan",
                              "source_filename": "fixture-cement-report-2025.pdf", "source_url": None}]}]}
FactTrail.model_validate(K_TRAIL)


@pytest.fixture
def k_transition(tmp_path, monkeypatch):
    """K with its alt-fuel fact and K1, K1's barriers read from an F-TA copy whose STL-R1 (EU-scored) names
    cement.alt_fuels (ruling D3; F-TA itself unchanged). Unratified, so each cell is its bundled score."""
    f_ta = tmp_path / "f_ta"
    shutil.copytree(FIXTURES / "f_ta", f_ta)
    raw = json.loads((f_ta / "rule_book.json").read_text(encoding="utf-8"))
    raw["actions"]["Steel"].append({"id": "cement.alt_fuels", "label": "Alternative and low-carbon kiln fuels"})
    raw["criteria"]["STL-R1"]["actions"].append("cement.alt_fuels")
    raw["fingerprint"] = compute_fingerprint(raw)
    (f_ta / "rule_book.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    assert read_and_validate(f_ta)[2] == []
    monkeypatch.setenv("ARP_TRANSITION_BARRIER_DATA_DIR", str(f_ta))
    get_settings.cache_clear()
    dataset.reset_caches()
    scores = {(s.code, s.region.value): s for s in dataset.load_scores()}
    barriers = [{"code": code, "region": EU, "rating": s.rating.value, "basis": s.basis, "evidence": s.evidence, "values": []}
                for code, c in load_rule_book(f_ta)[0].criteria.items() if "cement.alt_fuels" in c.actions and (s := scores.get((code, EU)))]
    yield in_scope("Cement", no_capex(80.0, "ACT Core D01.a, generic row", [
        {"id": "capex_share", "label": "Low-carbon R&D as a share of total capex", "used": None, "rule": None, "benchmark": 5.0,
         "ratio": None, "ratio_shown": None, "not_scored": "No reporting-year R&D figures", "fact_ids": []}]), [K_KPI], actions=[{
        "key": K1_KEY, "action_id": "cement.alt_fuels",
        "act_lever": {"wording": "Low/near-zero fuels incl. kiln electrification, waste fuels", "citation": "ACT Core methodology p.33"},
        "text": "We will raise alternative fuels to 30% of kiln heat by 2030.", "status": "planned", "year": 2030, "region": EU,
        "citation": "Fixture Cement Report 2025 p.9", "timeframe": "near term (2030)",
        "b02": b02((True, "near term (2030)", [128, 129]), NO_SAVING, NO_FUNDS), "barriers": barriers, "note": None,
        "fact_ids": [126, 127, 128, 129, 130]}])
    get_settings.cache_clear()
    dataset.reset_caches()


for _fixture in (C_TRANSITION, Q_TRANSITION, C_NO_PHASEOUT, C_NO_NET_ZERO, C_OFFSETS_CLEAR, X_TRANSITION, H_TRANSITION):  # the stubs cannot drift from the served model
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
    assert dri.get_by_role("button", name="1500 EUR million needed, 600 EUR million allocated").is_visible()  # AC-54
    carbon = section.get_by_role("row").filter(has_text="97.2 USD/tCO2 (90 EUR/tCO2)")
    assert carbon.get_by_role("cell").nth(4).inner_text() == "+25.2 USD/tCO2"  # AC-55
    assert dri.get_by_role("link", name="72 USD/tCO2 (EU ETS Market Report 2026, p. 12)").get_attribute("href").endswith(
        "/api/transition-barrier/documents/1#page=12")  # AC-43: the figure opens its barrier citation
    SCREENSHOT_P2.parent.mkdir(exist_ok=True)
    page.screenshot(path=str(SCREENSHOT_P2), full_page=True)


def test_ac89_ac119_delivery_checks(page):
    section = open_company(page, "C", company("C", "Fixture Steel AG", "2410"), [FACT], C_TRANSITION)
    section.get_by_text("Target progress 68.75% (ACT GE 1.4)", exact=True).wait_for()  # AC-89
    assert section.get_by_text(COVERAGE_TEXT, exact=True).is_visible()  # AC-119
    for cite in ("ACT GE 1.4, GE pp.31–34",
                 "Band points are ours, not ACT's (ACT GE pp.139–140)",  # AC-121
                 "ACT Core B02.c, Core p.37",  # AC-126
                 "ACT GE 9.2, GE pp.139–140; ACT Core D02.a, Core p.66",  # AC-127
                 "ACT GE 5.3, GE pp.89–90; IEA WEO 2024 Table B.2, p.329"):  # AC-128
        assert section.get_by_text(cite, exact=True).is_visible(), cite
    assert section.get_by_role("button", name="30%").is_visible()  # AC-120: T1's 30% opens its fact
    assert section.get_by_role("button", name="2035").is_visible()  # AC-129: O1's 2035 opens its fact
    carbon = section.get_by_role("row").filter(has_text="97.2 USD/tCO2 (90 EUR/tCO2)")
    assert [c.inner_text() for c in carbon.get_by_role("cell").all()[5:]] == [
        "140 USD/tCO2 (IEA NZE 2030, advanced economies)", "-42.8 USD/tCO2"]
    SCREENSHOT_DC.parent.mkdir(exist_ok=True)
    page.screenshot(path=str(SCREENSHOT_DC), full_page=True)


def test_ac112_no_phaseout(page):
    section = open_company(page, "C", company("C", "Fixture Steel AG", "2410"), [FACT], C_NO_PHASEOUT)
    section.get_by_text("No phase-out commitment disclosed", exact=True).wait_for()
    assert section.get_by_text("Band points are ours, not ACT's (ACT GE pp.139–140)", exact=True).count() == 0


def test_consistency_box(page):  # AC-146, AC-156, AC-147, AC-148
    section = open_company(page, "C", company("C", "Fixture Steel AG", "2410"), [FACT], C_TRANSITION)
    box = section.get_by_role("group", name="Consistency")
    box.wait_for()
    assert box.get_by_text(C_HEADER, exact=True).is_visible()  # AC-156
    assert "Offsets emphasised Does not state that credits are used only for residual emissions." in box.inner_text().replace("\n", " ")
    assert box.get_by_text("ACT Framework p.62; ACT Core p.26", exact=True).is_visible()  # AC-147
    assert box.get_by_role("button", name="facts").count() == 1
    assert box.get_by_text("No flag: " + "; ".join(FLAG_TITLES[:4]), exact=True).is_visible()  # AC-148
    assert box.get_by_text("Not checked", exact=False).count() == 0
    headline = section.get_by_text("Low-carbon capex 20% vs benchmark 80%: 0.25", exact=True)
    assert box.evaluate("(b, h) => !!(b.compareDocumentPosition(h) & Node.DOCUMENT_POSITION_FOLLOWING)", headline.element_handle())  # AC-146
    SCREENSHOT_FLAGS.parent.mkdir(exist_ok=True)
    page.screenshot(path=str(SCREENSHOT_FLAGS), full_page=True)


def test_ac157_not_checked_line(page):
    section = open_company(page, "C", company("C", "Fixture Steel AG", "2410"), [FACT], C_NO_NET_ZERO)
    box = section.get_by_role("group", name="Consistency")
    box.get_by_text("Not checked: Net zero without phase-out (No net-zero answer)", exact=True).wait_for()


def test_ac163_no_not_checked_line(page):
    section = open_company(page, "C", company("C", "Fixture Steel AG", "2410"), [FACT], C_OFFSETS_CLEAR)
    box = section.get_by_role("group", name="Consistency")
    box.get_by_text("Consistency: no check raises a flag", exact=True).wait_for()
    assert box.get_by_text("Not checked", exact=False).count() == 0


def test_ac44_q_is_not_in_scope(page):
    section = open_company(page, "Q", company("Q", "Fixture Foods SA", "1050"), [], Q_TRANSITION)
    section.get_by_text("Not in scope: ISIC 1050 is not in a transition-barrier sector", exact=True).wait_for()
    assert section.get_by_role("button").count() == 0


def kpi_table(section):
    return section.get_by_role("table", name="Delivery KPIs; choose a figure to open its source")


def cells(row):
    return [c.inner_text().strip() for c in row.get_by_role("cell").all()]


def marker_left(row):
    """The marker's inline `left` and its offset as a share of the bar's width, in percent (None without a marker)."""
    return row.get_by_role("cell").nth(3).evaluate("""td => {
        const bar = td.querySelector('[aria-hidden="true"]'), m = bar.firstElementChild;
        return m && [m.style.left, Math.round((m.offsetLeft / bar.clientWidth) * 1000) / 10];
    }""")


def shoot(page, section, variant):
    """The Delivery KPIs part, from its heading down to the Plan actions heading."""
    box = section.evaluate("""s => {
        const [kpis, plan] = ["Delivery KPIs", "Plan actions"].map((t) => [...s.querySelectorAll("h3")].find((h) => h.textContent === t).getBoundingClientRect());
        const r = s.getBoundingClientRect();
        return {x: r.left, y: kpis.top + scrollY - 8, width: r.width, height: plan.bottom - kpis.top + 16};
    }""")
    path = SCREENSHOTS[variant]
    path.parent.mkdir(exist_ok=True)
    page.screenshot(path=str(path), full_page=True, clip=box)


def test_ac187_ac200_ac201_ac203_k(page, k_transition):
    section = open_company(page, "K", company("K", "Fixture Cement SA", "2394"), [], k_transition)
    table = kpi_table(section)
    table.wait_for()
    headings = [h.inner_text() for h in section.get_by_role("heading", level=3).all()]
    assert headings[headings.index("Delivery KPIs") + 1] == "Plan actions"  # AC-187: directly before Plan actions
    assert [h.text_content() for h in table.get_by_role("columnheader").all()] == ["KPI", "Actual", "Year", "Range", "Action · barrier"]
    (row,) = table.get_by_role("row").all()[1:]
    label, actual, year, rng, action = cells(row)
    assert (label, actual, year, rng.split("\n")[0], action.split("\n")[0]) == (
        "Alternative-fuel share of kiln heat", "14%", "2025", "0% → 30%", "cement.alt_fuels")  # AC-187
    pairs = [f"{b['region']} {b['rating']}" for b in k_transition["actions"][0]["barriers"]]
    assert pairs and action.split("\n") == ["cement.alt_fuels", *pairs]  # AC-200
    assert rng.split("\n")[-1] == "ACT Cement v2.0, CEM 2.4a, p.50"  # AC-201: under the bar
    left, offset = marker_left(row)
    assert left == "46.7%" and abs(offset - 46.7) <= 1  # AC-203
    shoot(page, section, "k")


def test_ac188_k_fact_opens_its_page(page, k_transition):
    page.route(f"**/api/facts/{K_FACT}/trail", lambda r: r.fulfill(json=K_TRAIL))
    section = open_company(page, "K", company("K", "Fixture Cement SA", "2394"), [], k_transition)
    kpi_table(section).get_by_role("button", name="Alternative-fuel share of kiln heat: 14%").click()
    page.get_by_role("dialog", name=f"{K_DOC} — p. 12").wait_for()


def test_ac189_ac202_x_not_disclosed(page):
    section = open_company(page, "X", company("X", "Fixture Chemicals NV", "2011"), [], X_TRANSITION)
    table = kpi_table(section)
    table.wait_for()
    row = table.get_by_role("row").filter(has_text="Electrolytic share of methanol")
    assert cells(row)[1:3] == ["not disclosed", "—"]  # AC-189
    assert marker_left(row) is None  # AC-202
    assert marker_left(table.get_by_role("row").filter(has_text="Electrolytic share of ammonia"))[0] == "6%"
    shoot(page, section, "x")


def test_ac190_c_no_kpi(page):
    section = open_company(page, "C", company("C", "Fixture Steel AG", "2410"), [FACT], C_TRANSITION)
    heading = section.get_by_role("heading", name="Delivery KPIs", exact=True)
    heading.wait_for()
    assert heading.evaluate("h => h.nextElementSibling.textContent") == "No delivery KPI for this sector."
    assert kpi_table(section).count() == 0
    shoot(page, section, "c")


def test_ac191_h_at_390px(page):
    page.set_viewport_size({"width": 390, "height": 844})
    section = open_company(page, "H", company("H", "Fixture Trucks AB", "2910"), [], H_TRANSITION)
    table = kpi_table(section)
    table.wait_for()
    assert page.evaluate("document.documentElement.scrollWidth") <= 390  # no horizontal page scroll
    wrap = table.locator("xpath=..")
    assert wrap.evaluate("w => w.scrollWidth > w.clientWidth && getComputedStyle(w).overflowX === 'auto'")  # scrolls in its box
    wrap.evaluate("w => { w.scrollLeft = w.querySelectorAll('th')[3].offsetLeft - 8; }")  # the shot shows the wrapped range
    shoot(page, section, "h-390")
