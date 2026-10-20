"""Plan regions, barrier match, assumptions vs evidence and B02 (pure; spec sections 4-5, AC-24..AC-37, AC-49..AC-69)."""

from __future__ import annotations

import json
from decimal import Decimal
from itertools import count

import pytest

from arp.transition_alignment.actions import REGIONS, Cell, operating_regions, score_plan
from arp.transition_alignment.benchmarks import load_benchmarks
from arp.transition_alignment.capex import Fact
from tests.transition_alignment_helpers import FIXTURES, _reset, ta_dirs  # noqa: F401 - the fixture

TP = "Fixture Steel Transition Plan 2025"
EU, US, CN = REGIONS
CRITERIA = [
    ("STL-T1", ["steel.h2_dri"], list(REGIONS)),
    ("STL-R1", ["steel.h2_dri", "steel.scrap_eaf", "steel.ccus"], list(REGIONS)),
]
_ids = count(1)


@pytest.fixture(autouse=True)
def _bm(ta_dirs):  # noqa: F811
    yield


def fact(field_id, value, page, basis="", *, unit=None, amount=None, shown=None, year=None, doc=TP):
    return Fact(
        next(_ids), field_id, year, value, amount, unit, shown if shown is not None else str(value),
        f"{doc} p.{page}", basis, page,
    )


def money(field_id, millions, page, basis, currency="EUR"):
    v = Decimal(millions)
    return fact(field_id, v, page, basis, unit=currency, amount=v * 1_000_000, shown=f"{millions} {currency} million")


def action(n, text, page, action_id, status, year=None, region=None, extra=()):
    b = f"action:p1:{page}:1"
    out = [fact("ta_action_text", text, page, b), fact("ta_action_id", action_id, page, b),
           fact("ta_action_status", status, page, b)]
    if year is not None:
        out.append(fact("ta_action_year", Decimal(year), page, b, amount=Decimal(year), shown=str(year)))
    if region is not None:
        out.append(fact("ta_action_region", region, page, b))
    return out + [f(b) for f in extra]


def a1(**kw):
    args = dict(year=2028, region=EU, extra=(
        lambda b: money("ta_action_capex_needed", "1500", 13, b),
        lambda b: money("ta_action_capex_allocated", "600", 13, b),
        lambda b: fact("ta_action_ghg_saving", Decimal("3.5"), 14, b, unit="MtCO2e/yr", amount=Decimal("3.5"),
                       shown="3.5 MtCO2e/yr"),
    ))
    args.update(kw)
    return action(1, "We will commission a 2 Mt hydrogen-based DRI plant in Sweden by 2028.", 12, "steel.h2_dri",
                  "planned", **args)


def a2():
    return action(2, "Our electric arc furnace in Ohio has run on scrap since 2022.", 15, "steel.scrap_eaf",
                  "implemented", 2022, US)


def a3():
    return action(3, "We are studying carbon capture at our Tianjin plant.", 16, "steel.ccus", "planned", None, CN)


def carbon_price(value="90", unit="EUR/tCO2"):
    v = Decimal(value)
    return fact("ta_assumed_carbon_price", v, 20, f"region:{EU}", unit=unit, amount=v, shown=f"{value} {unit}", year=2030)


def h2_cost():
    return fact("ta_assumed_h2_cost", Decimal(3), 21, "region:any", unit="USD/kg H2", amount=Decimal(3), shown="3 USD/kg H2")


def operates():
    return [fact(f, True, 3, doc="Fixture Steel Annual Report 2025", shown="Yes")
            for f in ("ta_operates_eu", "ta_operates_us", "ta_operates_cn")]


def defaults():
    return [a1(), a2(), a3()], [carbon_price(), h2_cost()], operates()


def _value(fact_id, value, unit, document, page, doc_id):
    return {"fact": fact_id, "value": value, "unit": unit, "document": document, "page": page, "document_id": doc_id,
            "url": None, "counted": True}


HAND = {
    ("STL-R1", EU): "EU ETS price below the cost gap.",
    ("STL-R1", US): "No federal carbon price applies to steel.",
    ("STL-R1", CN): "National ETS price too low to matter.",
    ("STL-T1", EU): "Hydrogen cost above breakeven.",
    ("STL-T1", US): "Hydrogen cost well above breakeven.",
    ("STL-T1", CN): "No renewable hydrogen supply at scale.",
}
R1_EU = [
    _value("price", 72, "USD/tCO2", "EU ETS Market Report 2026", 12, 1),
    _value("applies", True, None, "EU ETS Market Report 2026", 12, 1),
    _value("levy", True, None, "EU ETS Market Report 2026", 12, 1),
]
T1_EU = [_value("h2_cost", 6, "USD/kg H2", "Hydrogen Cost Review 2026", 7, 5)]


def fta_cell(code, region):
    """F-TA after setup: STL-R1 and STL-T1 EU ratified (H, M); every other cell hand-rated L."""
    if (code, region) == ("STL-R1", EU):
        return Cell("H", "derived", "H holds", R1_EU)
    if (code, region) == ("STL-T1", EU):
        return Cell("M", "derived", "M holds", T1_EU)
    return Cell("L", "hand_rated", HAND[code, region], [])


def run(groups=None, assumptions=None, ops=None, cell=fta_cell):
    d_groups, d_assumptions, d_ops = defaults()
    b = load_benchmarks()
    conversions = json.loads((FIXTURES / "f_ta" / "rule_book.json").read_text(encoding="utf-8"))["conversions"]
    return score_plan(
        d_groups if groups is None else groups, d_assumptions if assumptions is None else assumptions,
        d_ops if ops is None else ops, criteria=CRITERIA, cell=cell, act_levers=b.act_levers,
        assumption_map=b.assumptions, conversions=conversions, doc_year=lambda _: 2026,
    )


def barriers(a):
    return [(x.code, x.region, x.rating, x.basis, x.evidence) for x in a.barriers]


def comparisons(a):
    return [(c.code, c.region, c.assumption, c.evidence, c.gap, c.reason) for c in a.comparisons]


def by_kind(plan, kind):
    return next(a for a in plan.assumptions if a.kind == kind)


def test_ac24_regions_and_order():
    groups, _, _ = defaults()
    plan = run(groups=list(reversed(groups)))  # input order does not matter: page, then fact_id
    assert plan.regions == [EU, US, CN]
    assert [a.action_id for a in plan.actions] == ["steel.h2_dri", "steel.scrap_eaf", "steel.ccus"]
    assert [a.citation for a in plan.actions] == [f"{TP} p.12", f"{TP} p.15", f"{TP} p.16"]
    assert plan.actions[0].key == "action:p1:12:1"
    assert plan.actions[0].status == "planned" and plan.actions[0].year == 2028 and plan.actions[0].region == EU


def test_ac25():
    a = run().actions[0]
    assert [b[:4] for b in barriers(a)] == [("STL-R1", EU, "H", "derived"), ("STL-T1", EU, "M", "derived")]
    v = a.barriers[0].values[0]
    assert (v["value"], v["unit"], v["document"], v["page"]) == (72, "USD/tCO2", "EU ETS Market Report 2026", 12)


def test_ac26():
    assert barriers(run().actions[1]) == [("STL-R1", US, "L", "hand_rated", "No federal carbon price applies to steel.")]


def test_ac27():
    assert barriers(run(groups=[a1(region=None), a2(), a3()]).actions[0]) == [
        ("STL-R1", EU, "H", "derived", "H holds"),
        ("STL-T1", EU, "M", "derived", "M holds"),
        ("STL-R1", US, "L", "hand_rated", "No federal carbon price applies to steel."),
        ("STL-T1", US, "L", "hand_rated", "Hydrogen cost well above breakeven."),
        ("STL-R1", CN, "L", "hand_rated", "National ETS price too low to matter."),
        ("STL-T1", CN, "L", "hand_rated", "No renewable hydrogen supply at scale."),
    ]


def test_ac28():
    plan = run(groups=[a1(region=None), a2(), a3()], ops=[])
    assert plan.regions == []
    assert plan.actions[0].barriers == [] and plan.actions[0].note == "No operating region disclosed"
    assert plan.actions[1].note is None  # A2 has its own region


def test_ac69():
    a = run(groups=[a1(region="other"), a2(), a3()]).actions[0]
    assert a.barriers == [] and a.note is None


def test_ac29():
    plan = run()
    assert plan.actions[1].act_lever.wording == "More scrap, process efficiency, zero-GHG power"
    assert plan.actions[1].act_lever.citation == "ACT Core methodology p.110"
    assert plan.actions[0].act_lever is None


def test_ac31():
    assert comparisons(by_kind(run(), "carbon_price")) == [
        ("STL-R1", EU, "97.2 USD/tCO2 (90 EUR/tCO2)", "72 USD/tCO2 (EU ETS Market Report 2026, p. 12)", "+25.2 USD/tCO2", None)
    ]
    a = by_kind(run(), "carbon_price")
    assert (a.region, a.year, a.citation) == (EU, 2030, f"{TP} p.20")


def test_ac32():
    a = by_kind(run(), "h2_cost")
    assert a.region is None
    assert comparisons(a) == [
        ("STL-T1", EU, "3 USD/kg H2", "6 USD/kg H2 (Hydrogen Cost Review 2026, p. 7)", "-3 USD/kg H2", None)
    ]


def test_ac33():
    got = comparisons(by_kind(run(groups=[a1(region=None), a2(), a3()]), "h2_cost"))
    assert [(c[0], c[1]) for c in got] == [("STL-T1", EU), ("STL-T1", US), ("STL-T1", CN)]
    assert got[1][3:5] == ("hand-rated, no figure: Hydrogen cost well above breakeven.", None)


def test_ac68():
    plan = run(assumptions=[carbon_price("90", "KRW/tCO2"), h2_cost()])
    assert comparisons(by_kind(plan, "carbon_price")) == [
        ("STL-R1", EU, None, "72 USD/tCO2 (EU ETS Market Report 2026, p. 12)", None, "Unit not convertible: KRW/tCO2")
    ]


def b02(a):
    return {k: (v.met, v.text) for k, v in a.b02.items()}


def test_ac34():
    a = run().actions[0]
    assert b02(a) == {
        "b": (True, "near term (2028)"),
        "c": (True, "3.5 MtCO2e/yr"),
        "d": (True, "1500 EUR million needed, 600 EUR million allocated"),
    }
    assert a.timeframe == "near term (2028)"


def test_ac35():
    assert b02(run().actions[1]) == {
        "b": (True, "implemented (2022)"),
        "c": (False, "No quantified GHG saving"),
        "d": (False, "No funding stated"),
    }


def test_ac49():
    a = run().actions[2]
    assert b02(a)["b"] == (False, "No timeframe: ignored")
    assert a.timeframe is None


def test_ac50():
    assert run().b02a.model_dump() == {
        "met": False, "text": "not met: 1 implemented, 1 planned with a timeframe (needs 3 and 1)"
    }


def test_ac59():
    a4 = action(4, "Since 2023 we recover waste heat at our Duisburg plant.", 17, "other", "implemented", 2023, EU)
    a5 = action(5, "Our Ohio plant has used renewable electricity since 2024.", 19, "other", "implemented", 2024, US)
    plan = run(groups=[a1(), a2(), a3(), a4, a5])
    assert plan.b02a.model_dump() == {"met": True, "text": "met: 3 implemented, 1 planned with a timeframe"}
    assert plan.actions[3].barriers == [] and plan.actions[3].act_lever is None


def test_ac60():
    assert b02(run(groups=[a1(year=2035), a2(), a3()]).actions[0])["b"] == (True, "long term (2035)")


def test_ac37():
    g = [f for f in a1() if f.field_id != "ta_action_capex_allocated"]
    assert b02(run(groups=[g, a2(), a3()]).actions[0])["d"] == (False, "No split of funds needed and allocated")


def test_ac63():
    g = [f for f in a1() if f.field_id != "ta_action_capex_allocated"]
    g.append(money("ta_action_capex_allocated", "650", 13, g[0].basis, "USD"))
    assert b02(run(groups=[g, a2(), a3()]).actions[0])["d"] == (False, "Needed and allocated in different currencies")


def test_group_without_text_not_listed():
    only_id = [f for f in a2() if f.field_id != "ta_action_text"]
    plan = run(groups=[a1(), only_id, a3()])
    assert [a.action_id for a in plan.actions] == ["steel.h2_dri", "steel.ccus"]
    # The unlisted action names STL-R1 in the US, but no comparison runs there.
    assert [c[:2] for c in comparisons(by_kind(plan, "carbon_price"))] == [("STL-R1", EU)]


def test_assumption_region_without_actions():
    us_price = fact("ta_assumed_carbon_price", Decimal(50), 20, "region:China", unit="USD/tCO2", amount=Decimal(50),
                    shown="50 USD/tCO2")
    plan = run(groups=[a1(), a2()], assumptions=[us_price])
    assert by_kind(plan, "carbon_price").comparisons == []


def test_unrated_cell_listed_null():
    def cell(code, region):
        return Cell(None, None, "", []) if (code, region) == ("STL-T1", EU) else fta_cell(code, region)

    plan = run(cell=cell)
    entry = plan.actions[0].barriers[1]
    assert (entry.code, entry.region, entry.rating, entry.basis, entry.evidence, entry.values) == (
        "STL-T1", EU, None, None, "", []
    )
    assert comparisons(by_kind(plan, "h2_cost"))[0][3:5] == ("no counted value", None)


def test_no_actions():
    plan = run(groups=[])
    assert plan.actions == [] and plan.b02a is None


def test_operating_regions_order_and_no():
    ops = [fact("ta_operates_cn", True, 3), fact("ta_operates_us", False, 3), fact("ta_operates_eu", True, 3)]
    assert operating_regions(ops) == [EU, CN]


def test_action_without_status_not_planned():
    g = [f for f in a1() if f.field_id != "ta_action_status"]
    plan = run(groups=[g, a2(), a3()])
    assert b02(plan.actions[0])["b"] == (False, "No timeframe: ignored")
    assert plan.actions[0].timeframe is None
    assert plan.b02a.text == "not met: 1 implemented, 0 planned with a timeframe (needs 3 and 1)"
