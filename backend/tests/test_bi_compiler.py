from __future__ import annotations

import json
from pathlib import Path

import pytest

from arp.bi.catalog import VIZ_ALLOWLIST
from arp.bi.compiler import compile_chart, compile_dashboard, compile_native_filters, plan_hash
from arp.bi.plan import ChartPlan, ChartSpec, NativeFilter

FIXTURES = Path(__file__).parent / "fixtures" / "bi"
EXP = "Exposure (EUR)"

# One canonical spec per viz_type; compile_chart must reproduce the fixture
# Task 4 verified against live Superset.
CANONICAL = {
    "big_number_total": dict(metrics=[EXP]),
    "echarts_timeseries_bar": dict(metrics=[EXP], groupby=["sector"]),
    "echarts_timeseries_line": dict(metrics=[EXP], groupby=["as_of_date", "portfolio_name"]),
    "heatmap_v2": dict(metrics=[EXP], groupby=["portfolio_name", "sector"]),
    "pie": dict(metrics=[EXP], groupby=["sector"]),
    "pivot_table_v2": dict(metrics=[EXP], groupby=["sector", "portfolio_name"]),
    "table": dict(metrics=[EXP, "Holdings"], groupby=["portfolio_name", "sector"]),
    "treemap_v2": dict(metrics=[EXP], groupby=["sector", "company_name"]),
}


def _spec(viz: str, **over) -> ChartSpec:
    return ChartSpec(title="t", viz_type=viz, dataset="holdings", **{**CANONICAL[viz], **over})


def test_canonical_covers_allowlist():
    assert set(CANONICAL) == set(VIZ_ALLOWLIST)


@pytest.mark.parametrize("viz", sorted(CANONICAL))
def test_compile_matches_verified_fixture(viz):
    fixture = json.loads((FIXTURES / f"{viz}.json").read_text())
    assert compile_chart(_spec(viz), 7) == fixture


def test_filters():
    p = compile_chart(_spec("pie", filters={"sector": "Energy"}), 7)
    assert p["adhoc_filters"] == [
        {"expressionType": "SIMPLE", "subject": "sector", "operator": "==", "comparator": "Energy", "clause": "WHERE"}
    ]


def test_no_time_range_field():
    # Superset 5 ignores a bare time_range with generic axes, so the plan does not offer one.
    assert "time_range" not in ChartSpec.model_fields


def _plan(filters, order=("a", "b")):
    charts = [ChartSpec(title=t, viz_type="pie", dataset="holdings", metrics=[EXP], filters=filters) for t in order]
    return ChartPlan(title="p", charts=charts)


def test_plan_hash_stable_and_order_independent_for_filters():
    h = plan_hash(_plan({"x": "1", "y": "2"}))
    assert len(h) == 12 and int(h, 16) >= 0
    assert h == plan_hash(_plan({"y": "2", "x": "1"}))
    assert h != plan_hash(_plan({"x": "1", "y": "3"}))
    assert h != plan_hash(_plan({"x": "1", "y": "2"}, order=("b", "a")))  # charts are positional


def test_dashboard_layout_two_per_row():
    pos = compile_dashboard([11, 12, 13, 14], ["a", "b", "c", "d"])
    assert pos["DASHBOARD_VERSION_KEY"] == "v2"
    assert pos["ROOT_ID"]["children"] == ["GRID_ID"]
    rows = pos["GRID_ID"]["children"]
    assert [pos[r]["children"] for r in rows] == [["CHART-11", "CHART-12"], ["CHART-13", "CHART-14"]]
    c = pos["CHART-13"]
    assert c["meta"] == {"chartId": 13, "width": 6, "height": 50, "sliceName": "c"}
    assert c["parents"] == ["ROOT_ID", "GRID_ID", rows[1]]
    assert pos[rows[0]]["parents"] == ["ROOT_ID", "GRID_ID"]
    json.dumps(pos)


def test_odd_chart_count_last_row_single():
    pos = compile_dashboard([1, 2, 3], ["a", "b", "c"])
    rows = pos["GRID_ID"]["children"]
    assert [len(pos[r]["children"]) for r in rows] == [2, 1]


@pytest.mark.parametrize(
    "viz,over",
    [
        ("echarts_timeseries_bar", dict(groupby=[])),
        ("echarts_timeseries_line", dict(groupby=[])),
        ("heatmap_v2", dict(groupby=["sector"])),
        ("pivot_table_v2", dict(groupby=["sector"])),
        ("pie", dict(groupby=[])),
        ("treemap_v2", dict(groupby=[])),
        ("big_number_total", dict(metrics=[])),
        ("table", dict(metrics=[])),
    ],
)
def test_missing_required_input_raises_clear_error(viz, over):
    with pytest.raises(ValueError, match=viz):
        compile_chart(_spec(viz, **over), 7)


def test_compile_native_filters_matches_verified_fixture():
    # Accepted and applied by Superset 5.0.0 (task-4 spike; test_native_filters_are_stored_and_applied).
    fixture = json.loads((FIXTURES / "native_filters.json").read_text())
    nf = [NativeFilter(name="Portfolio", dataset="holdings", column="portfolio_name")]
    assert compile_native_filters(nf, {"holdings": 1}) == fixture


def test_native_filter_ids_are_stable_and_unique():
    nf = [
        NativeFilter(name="Portfolio", dataset="holdings", column="portfolio_name"),
        NativeFilter(name="Portfolio", dataset="holdings_history", column="portfolio_name"),
        NativeFilter(name="Sector", dataset="holdings", column="sector"),
    ]

    def ids(ds_ids):
        return [f["id"] for f in compile_native_filters(nf, ds_ids)["native_filter_configuration"]]

    ids, again = ids({"holdings": 1, "holdings_history": 6}), ids({"holdings": 2, "holdings_history": 9})
    assert ids == again and len(set(ids)) == 3
    assert all(i.startswith("NATIVE_FILTER-") for i in ids)
    with pytest.raises(ValueError):
        compile_native_filters(nf[:1] * 2, {"holdings": 1})


def test_native_filter_on_unknown_dataset_names_filter_and_dataset():
    nf = [NativeFilter(name="Portfolio", dataset="holdings_history", column="portfolio_name")]
    with pytest.raises(ValueError, match="'Portfolio'.*'holdings_history'"):
        compile_native_filters(nf, {"holdings": 1})
