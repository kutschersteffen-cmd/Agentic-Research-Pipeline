"""Delivery KPIs (pure; spec 2026-10-21 delivery KPIs §3), over the bundled benchmarks."""

from __future__ import annotations

from decimal import Decimal

import pytest

from arp.transition_alignment.benchmarks import BUNDLED_DIR, load_benchmarks
from arp.transition_alignment.capex import Fact
from arp.transition_alignment.delivery_kpis import NO_KPI, score_delivery_kpis
from tests.test_transition_alignment_flags import _action


@pytest.fixture(scope="module")
def sectors():
    return load_benchmarks(BUNDLED_DIR).sectors


def fact(fact_id, value, year=2025, field_id="tc_alt_fuel_share_pct"):
    return Fact(fact_id, field_id, year, value, None, "%", "", None)


def cement(sectors, *facts, actions=()):
    (kpi,), note = score_delivery_kpis(sectors["Cement"], "2394", list(facts), list(actions))
    assert note is None
    return kpi


@pytest.mark.parametrize(("value", "shown", "position"), [
    (Decimal(14), 14, 46.7),
    ("14", 14, 46.7),  # Review Focus 1: a value stored as a string
    ("n/a", None, None),
    (True, None, None),
    (Decimal(35), 35, 100.0),  # Review Focus 2: clamped to 0-100
    (Decimal(-5), -5, 0.0),
])
def test_value_and_position(sectors, value, shown, position):
    kpi = cement(sectors, fact(7, value))
    assert (kpi.value, kpi.position_pct, kpi.year, kpi.fact_ids) == (shown, position, 2025, [7])


def test_latest_year_wins(sectors):
    kpi = cement(sectors, fact(1, Decimal(10), 2024), fact(2, Decimal(14), 2025), fact(3, Decimal(9), None))
    assert (kpi.value, kpi.year, kpi.fact_ids) == (14, 2025, [2])


def test_tie_goes_to_lowest_fact_id(sectors):
    kpi = cement(sectors, fact(9, Decimal(16)), fact(4, Decimal(14)))
    assert (kpi.value, kpi.fact_ids) == (14, [4])


def test_no_fact(sectors):
    kpi = cement(sectors, fact(1, Decimal(50), field_id="tc_saf_share_pct"))
    assert (kpi.value, kpi.year, kpi.fact_ids, kpi.position_pct, kpi.range_text) == (None, None, [], None, "0% → 30%")


def test_action_keys_in_actions_order(sectors):
    acts = [_action("b", 2030, None), _action("a", 2030, None), _action("c", 2030, None)]
    acts[0].action_id, acts[1].action_id, acts[2].action_id = "cement.alt_fuels", "cement.ccs", "cement.alt_fuels"
    assert cement(sectors, actions=acts).action_keys == ["b", "c"]


@pytest.mark.parametrize(("sector", "isic", "ids", "ranges"), [
    ("Cement", "2394", ["alt_fuel_share"], ["0% → 30%"]),  # one point without a year
    ("Heavy-Duty Road Transport", "4923", ["fleet_lc_share"], ["0% → 95% (2040)"]),  # one point with a year
    ("Heavy-Duty Road Transport", "2910", ["zev_sales_share"], ["0% → 37% (2030) → 65% (2035) → 100% (2050)"]),
    ("Chemicals", "2011", ["nh3_electrolytic", "meoh_electrolytic", "electrolysis_lc_power"],
     ["0% → 50%", "0% → 75%", "0% → 90%"]),
])
def test_matching_and_point_shapes(sectors, sector, isic, ids, ranges):
    kpis, note = score_delivery_kpis(sectors[sector], isic, [], [])
    assert ([k.id for k in kpis], [k.range_text for k in kpis], note) == (ids, ranges, None)


def test_position_against_last_point(sectors):
    (kpi,), _ = score_delivery_kpis(sectors["Heavy-Duty Road Transport"], "2910",
                                    [fact(1, Decimal(4), field_id="tc_zev_sales_share_pct")], [])
    assert kpi.position_pct == 4.0


def test_no_kpi_note(sectors):
    assert score_delivery_kpis(sectors["Steel"], "2410", [], []) == ([], NO_KPI)
    assert NO_KPI == "No delivery KPI for this sector."
