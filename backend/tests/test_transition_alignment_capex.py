"""D01.a capex score, R&D tests and redlines over fact rows (pure; spec section 3, AC-9..AC-20, AC-61, AC-65, AC-70)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from arp.schemas.transition_alignment import ShareOut
from arp.transition_alignment.benchmarks import load_benchmarks
from arp.transition_alignment.capex import Fact, combine_years, score_capex, share_for
from tests.transition_alignment_helpers import _reset, ta_dirs  # noqa: F401 - the fixture

AR = "Fixture Steel Annual Report 2025 p."
TP = "Fixture Steel Transition Plan 2025 p.18"


@pytest.fixture(autouse=True)
def _bm(ta_dirs):  # noqa: F811
    yield


def steel():
    return load_benchmarks().sectors["Steel"]


def cement():
    return load_benchmarks().sectors["Cement"]


def power():
    return load_benchmarks().sectors["Power & Utilities"]


_ids = iter(range(1, 10_000))


def money(field_id, year, millions, citation, currency="EUR"):
    v = Decimal(millions)
    return Fact(next(_ids), field_id, year, v, v * 1_000_000, currency, f"{millions} {currency} million", citation)


def pct(field_id, year, value, citation):
    v = Decimal(value)
    return Fact(next(_ids), field_id, year, v, v, "%", f"{value} %", citation)


def yes_no(field_id, value, citation, year=2025):
    return Fact(next(_ids), field_id, year, value, None, None, "Yes" if value else "No", citation)


def defaults_c() -> list[Fact]:
    return [
        money("tc_capex_total", 2025, 1000, AR + "44"),
        money("tc_lowcarbon_capex", 2025, 120, AR + "45"),
        pct("tc_lowcarbon_capex_share_pct", 2025, 12, AR + "45"),
        money("tc_carbon_intensive_capex", 2025, 300, AR + "46"),
        yes_no("tc_new_blast_furnace", False, AR + "48"),
        money("tc_rnd_total", 2025, 50, AR + "50"),
        money("tc_lowcarbon_rnd", 2025, 30, AR + "50"),
        money("tc_lowcarbon_rnd_early", 2025, 15, AR + "50"),
        money("tc_rnd_total", 2024, 40, AR + "51"),
        money("tc_lowcarbon_rnd", 2024, 20, AR + "51"),
        money("tc_lowcarbon_rnd_early", 2024, 12, AR + "51"),
        money("tc_capex_total_planned", 2026, 1100, TP),
        pct("tc_lowcarbon_capex_share_pct_planned", 2026, 20, TP),
    ]


def without(facts, *keys):
    """Drop facts by field id, or by (field id, year)."""
    return [f for f in facts if f.field_id not in keys and (f.field_id, f.year) not in keys]


def by_field(facts, field_id, year):
    return next(f for f in facts if (f.field_id, f.year) == (field_id, year))


def rnd(c, test_id):
    return next(t for t in c.rnd_tests if t.id == test_id)


def test_ac9():
    c = score_capex(defaults_c(), steel(), "x")
    assert (c.reporting_year, c.share_used, c.rule, c.benchmark.value, c.ratio_shown) == (
        2025, 20, "RY+1 higher: RY+1 used", 80, "0.25",
    )
    assert c.headline == "Low-carbon capex 20% vs benchmark 80%: 0.25"
    assert (c.share_used_shown, c.ratio, c.not_scored, c.licence_note) == ("20", 0.25, None, "x")
    assert c.share_ry1.source == "disclosed"


def test_ac10():
    facts = without(defaults_c(), "tc_lowcarbon_capex_share_pct_planned") + [
        pct("tc_lowcarbon_capex_share_pct_planned", 2026, 8, TP)
    ]
    c = score_capex(facts, steel(), "x")
    assert (c.share_used, c.rule, c.ratio_shown) == (10, "RY+1 lower: average of RY and RY+1", "0.13")


def test_ry1_equal():
    facts = without(defaults_c(), "tc_lowcarbon_capex_share_pct_planned") + [
        pct("tc_lowcarbon_capex_share_pct_planned", 2026, 12, TP)
    ]
    c = score_capex(facts, steel(), "x")
    assert (c.share_used, c.rule) == (12, "RY+1 equal: RY used")


def test_ac11():
    c = score_capex(without(defaults_c(), "tc_lowcarbon_capex_share_pct_planned"), steel(), "x")
    assert (c.share_used, c.rule, c.ratio_shown, c.share_ry1) == (12, "Only RY known: RY used", "0.15", None)


def test_ac12():
    facts = without(defaults_c(), "tc_lowcarbon_capex_share_pct")
    c = score_capex(facts, steel(), "x")
    ids = [by_field(facts, "tc_lowcarbon_capex", 2025).fact_id, by_field(facts, "tc_capex_total", 2025).fact_id]
    assert c.share_ry == ShareOut(value=12, source="computed from amounts", fact_ids=ids)
    assert c.share_used == 20


def test_disclosed_share_wins():
    facts = defaults_c()
    c = score_capex(facts, steel(), "x")
    assert c.share_ry == ShareOut(
        value=12, source="disclosed", fact_ids=[by_field(facts, "tc_lowcarbon_capex_share_pct", 2025).fact_id]
    )


def test_ac13():
    facts = without(
        defaults_c(),
        ("tc_lowcarbon_capex_share_pct", 2025),
        ("tc_lowcarbon_capex", 2025),
        ("tc_capex_total", 2025),
    )
    c = score_capex(facts, steel(), "x")
    assert (c.ratio, c.ratio_shown, c.share_used, c.rule) == (None, None, None, None)
    assert c.not_scored == "No reporting-year low-carbon capex share"
    assert c.headline == "Capex not scored: No reporting-year low-carbon capex share"


def test_ac14():
    c = score_capex([pct("tc_lowcarbon_capex_share_pct", 2025, 97, "Fixture Power Annual Report 2025 p.3")], power(), "x")
    assert (c.benchmark.value, c.ratio_shown, c.ratio) == (95, "1", 1)


def test_ac15():
    c = score_capex(defaults_c(), steel(), "x")
    got = {(a.field_id, a.year): a for a in c.amounts}
    ci = got[("tc_carbon_intensive_capex", 2025)]
    assert (ci.shown, ci.citation) == ("300 EUR million", AR + "46")
    assert got[("tc_capex_total_planned", 2026)].shown == "1100 EUR million"


def test_amounts_order_and_window():
    facts = defaults_c() + [money("tc_capex_total", 2023, 900, AR + "1")]  # RY-2: outside RY-1..RY+1
    c = score_capex(facts, steel(), "x")
    assert [(a.field_id, a.year) for a in c.amounts] == [
        ("tc_capex_total", 2025),
        ("tc_lowcarbon_capex", 2025),
        ("tc_capex_total_planned", 2026),
        ("tc_carbon_intensive_capex", 2025),
        ("tc_rnd_total", 2024),
        ("tc_rnd_total", 2025),
        ("tc_lowcarbon_rnd", 2024),
        ("tc_lowcarbon_rnd", 2025),
        ("tc_lowcarbon_rnd_early", 2024),
        ("tc_lowcarbon_rnd_early", 2025),
    ]


def test_ac70():
    c = score_capex(without(defaults_c(), "tc_carbon_intensive_capex"), steel(), "x")
    assert all(a.field_id != "tc_carbon_intensive_capex" for a in c.amounts)


def test_ac16():
    c = score_capex(defaults_c(), steel(), "x")
    lc, early = rnd(c, "lc_share"), rnd(c, "early_stage")
    assert (lc.used, lc.rule, lc.ratio_shown, lc.benchmark, lc.not_scored) == (60, "RY higher: RY used", "0.75", 80, None)
    assert (early.used, early.rule, early.ratio_shown) == (55, "RY lower: average of RY-1 and RY", "0.85")


def test_rnd_disclosed_share_stands_in():
    facts = defaults_c() + [pct("tc_lowcarbon_rnd_share_pct", 2025, 40, AR + "50")]
    lc = rnd(score_capex(facts, steel(), "x"), "lc_share")
    assert (lc.used, lc.rule) == (45, "RY lower: average of RY-1 and RY")  # 2024 = 20/40 = 50, 2025 disclosed 40


def test_rnd_equal_and_only_ry():
    facts = without(defaults_c(), ("tc_lowcarbon_rnd", 2024)) + [money("tc_lowcarbon_rnd", 2024, 24, AR + "51")]
    c = score_capex(facts, steel(), "x")
    assert (rnd(c, "lc_share").used, rnd(c, "lc_share").rule) == (60, "RY equal: RY used")  # 24/40 = 60
    facts = without(defaults_c(), ("tc_rnd_total", 2024))
    assert rnd(score_capex(facts, steel(), "x"), "lc_share").rule == "Only RY known: RY used"


def test_ac17():
    facts = [money("tc_lowcarbon_rnd", 2025, 40, "K p.1"), money("tc_capex_total", 2025, 1000, "K p.2")]
    t = rnd(score_capex(facts, cement(), "x"), "capex_share")
    assert (t.used, t.rule, t.ratio_shown) == (4, "Only RY known: RY used", "0.8")
    assert t.fact_ids == [f.fact_id for f in facts]


def test_ac61():
    c = score_capex(
        without(defaults_c(), ("tc_rnd_total", 2025), ("tc_lowcarbon_rnd", 2025), ("tc_lowcarbon_rnd_early", 2025)),
        steel(),
        "x",
    )
    assert c.reporting_year == 2025
    for tid in ("lc_share", "early_stage"):
        t = rnd(c, tid)
        assert (t.not_scored, t.used, t.rule, t.ratio_shown) == ("No reporting-year R&D figures", None, None, None)


def test_ac65():
    facts = defaults_c()
    c = score_capex(facts, steel(), "x")
    assert [(r.id, r.status, r.citation) for r in c.redlines] == [("stl_bf", "not breached", AR + "48")]
    assert c.redlines[0].fact_id == by_field(facts, "tc_new_blast_furnace", 2025).fact_id
    assert c.redlines[0].source == "owner-defined (2026-10-19)"


def test_ac19_ac20():
    coal = yes_no("tc_new_unabated_coal", True, "Fixture Power Annual Report 2025 p.9")
    r = score_capex([coal], power(), "x").redlines[0]
    assert (r.id, r.status, r.citation, r.fact_id) == ("pwr_coal", "breached", "Fixture Power Annual Report 2025 p.9", coal.fact_id)
    r = score_capex([], power(), "x").redlines[0]
    assert (r.status, r.citation, r.fact_id) == ("no disclosure", None, None)


def test_redline_value_none_is_no_disclosure():
    r = score_capex([yes_no("tc_new_unabated_coal", None, "p.9")], power(), "x").redlines[0]
    assert (r.status, r.citation, r.fact_id) == ("no disclosure", None, None)


def test_redline_uses_latest_year():
    old = yes_no("tc_new_unabated_coal", False, "old", year=2023)
    new = yes_no("tc_new_unabated_coal", True, "new", year=2025)
    assert score_capex([new, old], power(), "x").redlines[0].status == "breached"


def test_mixed_currency_and_zero_total():
    facts = without(defaults_c(), "tc_lowcarbon_capex_share_pct", "tc_lowcarbon_capex") + [
        money("tc_lowcarbon_capex", 2025, 120, AR + "45", currency="USD")
    ]
    c = score_capex(facts, steel(), "x")
    assert (c.share_ry, c.ratio, c.not_scored) == (None, None, "No reporting-year low-carbon capex share")
    facts = without(defaults_c(), "tc_lowcarbon_capex_share_pct", "tc_capex_total") + [
        money("tc_capex_total", 2025, 0, AR + "44")
    ]
    c = score_capex(facts, steel(), "x")
    assert (c.share_ry, c.not_scored) == (None, "No reporting-year low-carbon capex share")


def test_share_is_exact():
    facts = {
        ("tc_lowcarbon_capex", 2025): money("tc_lowcarbon_capex", 2025, 70, "a"),
        ("tc_capex_total", 2025): money("tc_capex_total", 2025, 1000, "b"),
    }
    assert share_for(facts, 2025, planned=False).value == 7
    assert repr(share_for(facts, 2025, planned=False).value) == "7.0"


def test_no_facts():
    c = score_capex([], steel(), "x")
    assert (c.reporting_year, c.share_ry, c.amounts) == (None, None, [])
    assert c.headline == "Capex not scored: No reporting-year low-carbon capex share"
    assert all(t.not_scored == "No reporting-year R&D figures" for t in c.rnd_tests)
    assert [r.status for r in c.redlines] == ["no disclosure"]


def test_duplicate_year_keeps_lowest_fact_id():
    a = pct("tc_lowcarbon_capex_share_pct", 2025, 12, "a")
    b = pct("tc_lowcarbon_capex_share_pct", 2025, 50, "b")
    assert score_capex([b, a], steel(), "x").share_used == 12


def test_combine_years():
    d = Decimal
    assert combine_years(d(10), None) == 10
    assert combine_years(None, d(10)) == 10
    assert combine_years(None, None) is None
    assert combine_years(d(12), d(20)) == 20
    assert combine_years(d(12), d(12)) == 12
    assert combine_years(d(12), d(8)) == 10
