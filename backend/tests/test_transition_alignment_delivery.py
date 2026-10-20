"""Target progress, abatement coverage, phase-out and scenario carbon price (pure; spec 2026-10-20 sections 2-6)."""

from __future__ import annotations

import json
from decimal import Decimal
from itertools import count

from arp.schemas.transition_alignment import ActionOut, AssumptionOut, B02Out
from arp.transition_alignment.actions import REGIONS
from arp.transition_alignment.benchmarks import ScenarioGroup
from arp.transition_alignment.capex import Fact
from arp.transition_alignment.delivery import scenario_entries, score_coverage, score_phaseouts, score_targets
from tests.transition_alignment_helpers import FIXTURES

P1 = "Fixture Steel Transition Plan 2025"
P2 = "Fixture Steel Annual Report 2025"
P7 = "Fixture Power Transition Plan 2025"
EU, US, CN = REGIONS
PLAN_YEAR = 2026
_ids = count(1)


def fact(field_id, value, page, basis="", *, unit=None, year=None, doc=P1, shown=None):
    amount = value if isinstance(value, Decimal) else None
    if shown is None:
        shown = f"{value} {unit}" if unit else str(value)
    return Fact(next(_ids), field_id, year, value, amount, unit, shown, f"{doc} p.{page}", basis, page)


def num(field_id, value, page, basis="", **kw):
    return fact(field_id, Decimal(str(value)), page, basis, **kw)


# --- targets -------------------------------------------------------------------------------------------------------

def target(page, scope="S1+2", pct=30, year=2030, base_year=2019, base=20, base_unit="MtCO2e", set_year=2021, drop=()):
    b = f"target:p1:{page}:1"
    values = {
        "ta_target_scope": lambda: fact("ta_target_scope", scope, page, b),
        "ta_target_pct": lambda: num("ta_target_pct", pct, page, b, unit="%"),
        "ta_target_year": lambda: num("ta_target_year", year, page, b),
        "ta_target_base_year": lambda: num("ta_target_base_year", base_year, page, b),
        "ta_target_base_emissions": lambda: num("ta_target_base_emissions", base, page, b, unit=base_unit),
        "ta_target_set_year": lambda: num("ta_target_set_year", set_year, page, b),
    }
    return [make() for fid, make in values.items() if fid not in drop]


def t1(**kw):
    return target(22, **kw)


def t0(**kw):
    return target(23, **{"pct": 10, "year": 2023, "set_year": 2020, **kw})


def emissions(drop=()):
    rows = [("tp_h_scope1_emissions", 2025, 17_500_000, 52), ("tp_h_scope2_emissions", 2025, 500_000, 52),
            ("tp_h_scope1_emissions", 2023, 18_000_000, 53), ("tp_h_scope2_emissions", 2023, 500_000, 53)]
    return [num(fid, v, page, unit="tCO2e", year=y, doc=P2) for fid, y, v, page in rows if (fid, y) not in drop]


def targets(groups=None, em=None):
    return score_targets([t1(), t0()] if groups is None else groups, emissions() if em is None else em, PLAN_YEAR)


def by_page(ts, page):
    return next(t for t in ts if t.citation == f"{P1} p.{page}")


def test_target_order_and_fields():
    ts, _ = targets([t0(), t1()])
    assert [t.citation for t in ts] == [f"{P1} p.22", f"{P1} p.23"]
    assert ts[0].key == "target:p1:22:1"
    assert (ts[0].scope, ts[0].pct, ts[0].year, ts[0].base_year, ts[0].base_emissions_shown) == (
        "S1+2", 30, 2030, 2019, "20 MtCO2e")
    assert len(ts[0].fact_ids) == 6


def test_ac90_t0_past():
    t = by_page(targets()[0], 23)
    assert (t.kind, t.ratio, t.score) == ("past", "0.75", 50)


def test_ac91_t1_running():
    t = by_page(targets()[0], 22)
    assert (t.kind, t.ratio, t.score) == ("running", "0.75", 75)


def test_ac73_overall():
    assert targets()[1].text == "Target progress 68.75% (ACT GE 1.4)"
    assert targets()[1].score == 68.75


def test_ac74_no_2023_scope2():
    t = by_page(targets(em=emissions(drop={("tp_h_scope2_emissions", 2023)}))[0], 23)
    assert (t.score, t.reason) == (None, "No emissions for 2023")


def test_ac122_overall_without_t0():
    assert targets(em=emissions(drop={("tp_h_scope2_emissions", 2023)}))[1].text == "Target progress 75% (ACT GE 1.4)"


def test_ac75_no_base_emissions():
    t = by_page(targets([t1(drop={"ta_target_base_emissions"}), t0()])[0], 22)
    assert (t.score, t.reason) == (None, "No base-year emissions")


def test_ac92_overall_past_only():
    assert targets([t1(drop={"ta_target_base_emissions"}), t0()])[1].text == "Target progress 50% (ACT GE 1.4)"


def test_ac123_coverage_no_base_emissions():
    ts, _ = targets([t1(drop={"ta_target_base_emissions"}), t0()])
    assert score_coverage(ts, actions(), savings()).reason == "No base-year emissions"


def test_ac76_scope3():
    t = by_page(targets([t1(scope="S1+2+3"), t0()])[0], 22)
    assert (t.kind, t.score, t.reason) == (None, None, "Scope 3 target: progress not computed")


def test_ac93_neither_past_nor_running():
    t = by_page(targets([t1(year=2035, set_year=2026), t0()])[0], 22)
    assert (t.kind, t.reason) == (None, "Target year 2035 neither past nor running")


def test_ac94_no_pct():
    t = by_page(targets([t1(drop={"ta_target_pct"}), t0()])[0], 22)
    assert (t.score, t.reason) == (None, "Incomplete target")


def test_ac99_set_year_defaults_to_plan_year():
    t = by_page(targets([t1(drop={"ta_target_set_year"}), t0()])[0], 22)
    assert (t.kind, t.reason) == (None, "Target year 2030 neither past nor running")


def test_ac100_base_in_tco2e():
    t = by_page(targets([t1(base=20_000_000, base_unit="tCO2e"), t0()])[0], 22)
    assert (t.ratio, t.score) == ("0.75", 75)


def test_ac103_no_counted_target():
    assert targets([]) == ([], None)


def test_rf2_zero_pct_is_incomplete():
    t = by_page(targets([t1(pct=0), t0()])[0], 22)
    assert (t.kind, t.score, t.reason) == (None, None, "Incomplete target")


def test_rf3_ry_needs_both_scopes():
    em = emissions() + [num("tp_h_scope2_emissions", 500_000, 54, unit="tCO2e", year=2026, doc=P2)]
    t = by_page(targets(em=em)[0], 22)
    assert (t.kind, t.ratio, t.score) == ("running", "0.75", 75)  # RY stays 2025: 2026 has no scope 1


# --- coverage ------------------------------------------------------------------------------------------------------

def _action(key, year):
    b = B02Out(met=False, text="")
    return ActionOut(key=key, action_id=None, act_lever=None, text=key, status="planned", year=year, region=None,
                     citation=None, timeframe=None, b02={"b": b, "c": b, "d": b}, barriers=[], note=None, fact_ids=[])


def actions(a1_year=2028):
    return [_action("action:p1:12:1", a1_year), _action("action:p1:15:1", 2022), _action("action:p1:16:1", None)]


def savings(value="3.5", unit="MtCO2e/yr"):
    return {"action:p1:12:1": num("ta_action_ghg_saving", value, 14, "action:p1:12:1", unit=unit)}


def coverage(groups=None, acts=None, saves=None):
    ts, _ = targets(groups)
    return score_coverage(ts, actions() if acts is None else acts, savings() if saves is None else saves)


def test_ac77_coverage_text():
    c = coverage()
    assert c.text == "Listed actions cover 58.33% of the 2030 target gap (3.5 of 6 MtCO2e/yr)"
    assert (c.target_key, c.percent, c.reason) == ("target:p1:22:1", 58.33, None)


def test_ac101_coverage_actions():
    assert [(a.key, a.summed, a.reason) for a in coverage().actions] == [
        ("action:p1:12:1", True, None),
        ("action:p1:15:1", False, "No quantified saving"),
        ("action:p1:16:1", False, "No quantified saving"),
    ]
    assert coverage().actions[0].saving_shown == "3.5 MtCO2e/yr"


def test_ac78_after_target_year():
    a = coverage(acts=actions(a1_year=2031)).actions[0]
    assert (a.summed, a.reason) == (False, "After the target year")


def test_ac124_no_summable_action():
    c = coverage(acts=actions(a1_year=2031))
    assert (c.percent, c.reason) == (None, "No summable action")


def test_ac102_pct_saving():
    assert coverage(saves=savings("10", "%")).actions[0].reason == "Saving in % not summed"


def test_pct_saving_without_value_is_no_saving():  # spec §4: "no saving" is checked before "% saving"
    assert coverage(saves={"action:p1:12:1": fact("ta_action_ghg_saving", None, 14, unit="%")}).actions[0].reason == (
        "No quantified saving")


def test_ac79_no_running_target():
    c = coverage(groups=[])
    assert (c.percent, c.reason) == (None, "No running target")


def test_rf1_tie_uses_earlier_page():
    late = target(30, pct=50)  # same target year 2030, later page
    c = coverage(groups=[late, t1(), t0()])
    assert c.target_key == "target:p1:22:1"


# --- phase-outs ----------------------------------------------------------------------------------------------------

def phaseout(page=24, activity="blast furnace steelmaking", share=50, year=2035, method="closure", doc=P1, drop=()):
    b = f"phaseout:p1:{page}:1"
    values = {
        "ta_phaseout_activity": lambda: fact("ta_phaseout_activity", activity, page, b, doc=doc),
        "ta_phaseout_share_pct": lambda: num("ta_phaseout_share_pct", share, page, b, unit="%", doc=doc),
        "ta_phaseout_year": lambda: num("ta_phaseout_year", year, page, b, doc=doc),
        "ta_phaseout_method": lambda: fact("ta_phaseout_method", method, page, b, doc=doc),
    }
    return [make() for fid, make in values.items() if fid not in drop]


def o1(sector="Steel", **kw):
    return score_phaseouts([phaseout(**kw)], sector, PLAN_YEAR)[0]


def o2(**kw):
    args = {"page": 4, "activity": "coal power", "share": 100, "year": 2038, "doc": P7, **kw}
    return score_phaseouts([phaseout(**args)], "Power & Utilities", PLAN_YEAR)[0]


def test_ac80_o1():
    o = o1()
    assert (o.share_points, o.date_points, o.score) == (25, 75, 40)
    assert (o.key, o.activity, o.share, o.year, o.method, o.citation) == (
        "phaseout:p1:24:1", "blast furnace steelmaking", 50, 2035, "closure", f"{P1} p.24")


def test_ac104_no_sector_timeline():
    assert o1().timeline_text == "No ACT Core sector timeline"


def test_ac81_o2():
    o = o2()
    assert (o.share_points, o.date_points, o.score) == (100, 50, 85)


def test_ac105_meets_timeline():
    assert o2().timeline_text == "Meets the ACT Core timeline (2040)"


def test_ac106_share_50_does_not_meet():
    assert o2(share=50).timeline_text == "Does not meet the ACT Core timeline (2040)"


def test_ac107_year_2031():
    assert o1(year=2031).date_points == 100


def test_ac108_share_25_26():
    assert (o1(share=25).share_points, o1(share=26).share_points) == (0, 25)


def test_ac109_share_95_96():
    assert (o1(share=95).share_points, o1(share=96).share_points) == (75, 100)


def test_ac110_year_2046_2047():
    assert (o1(year=2046).date_points, o1(year=2047).date_points) == (25, 0)


def test_ac82_sale_note():
    assert o1(method="sale").note == "Sale, not closure: ACT counts this negatively (GE p.139)"
    assert o1().note is None


def test_ac111_no_share():
    o = o1(drop={"ta_phaseout_share_pct"})
    assert (o.score, o.reason) == (None, "No share stated")


def test_no_year_stated():
    o = o1(drop={"ta_phaseout_year"})
    assert (o.score, o.reason) == (None, "No year stated")


def test_rf4_year_before_plan_year():
    assert o1(year=2020).date_points == 100


def test_timelines():
    assert o1(sector="Shipping", share=100, year=2040).timeline_text == "Meets the ACT Core timeline (2040)"
    assert o1(sector="Heavy-Duty Road Transport", share=100, year=2036).timeline_text == (
        "Does not meet the ACT Core timeline (2035)")


# --- scenario carbon price -----------------------------------------------------------------------------------------

GROUPS = [ScenarioGroup(**g) for g in
          json.loads((FIXTURES / "bm_s" / "benchmarks.json").read_text(encoding="utf-8"))["scenario_prices"]]
CONVERSIONS = json.loads((FIXTURES / "f_ta" / "rule_book.json").read_text(encoding="utf-8"))["conversions"]


def carbon_price(value="90", unit="EUR/tCO2", region=EU, year=2030):
    return fact("ta_assumed_carbon_price", Decimal(value), 20, f"region:{region}", unit=unit, year=year,
                shown=f"{value} {unit}")


def _out(f):
    kind = f.field_id.removeprefix("ta_assumed_")
    region = f.basis.removeprefix("region:")
    return AssumptionOut(kind=kind, region=region if region in REGIONS else None, year=f.year, citation=f.citation,
                         fact_id=f.fact_id, comparisons=[])


def scenario(f, regions=(EU, US, CN)):
    return [(s.region, s.year, s.scenario, s.assumption, s.gap, s.reason)
            for s in scenario_entries(_out(f), f, list(regions), GROUPS, CONVERSIONS, PLAN_YEAR)]


def test_ac84_default_carbon_price():
    assert scenario(carbon_price()) == [
        (EU, 2030, "140 USD/tCO2 (IEA NZE 2030, advanced economies)", "97.2 USD/tCO2 (90 EUR/tCO2)", "-42.8 USD/tCO2",
         None)]


def test_ac85_interpolated():
    assert scenario(carbon_price(year=2045))[0][2] == "227.5 USD/tCO2 (IEA NZE 2045, advanced economies)"


def test_ac86_no_year():
    assert scenario(carbon_price(year=None)) == [
        (EU, None, None, "97.2 USD/tCO2 (90 EUR/tCO2)", None, "No scenario price for (no year)")]


def test_ac95_before_2030():
    assert scenario(carbon_price(year=2028))[0][5] == "No scenario price for 2028"


def test_ac96_zero_gap():
    (_, _, s, a, gap, reason), = scenario(carbon_price("90", "USD/tCO2", CN))
    assert (s, a, gap, reason) == ("90 USD/tCO2 (IEA NZE 2030, selected EMDE)", "90 USD/tCO2", "0 USD/tCO2", None)


def test_ac97_hydrogen_has_no_scenario():
    h2 = fact("ta_assumed_h2_cost", Decimal(3), 21, "region:any", unit="USD/kg H2")
    assert scenario(h2) == []


def test_rf5_region_any_one_entry_per_operating_region():
    rows = scenario(carbon_price(region="any"), regions=(EU, US, CN))
    assert [r[0] for r in rows] == [EU, US, CN]
    assert rows[2][2] == "90 USD/tCO2 (IEA NZE 2030, selected EMDE)"


def test_unconvertible_assumption():
    rows = scenario(carbon_price(unit="GBP/tCO2"))
    assert rows == [(EU, 2030, None, None, None, "Unit not convertible: GBP/tCO2")]
