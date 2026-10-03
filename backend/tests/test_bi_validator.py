from __future__ import annotations

import pytest

from arp.bi.plan import MAX_CHARTS, ChartPlan, ChartSpec, DatasetMeta
from arp.bi.validator import validate_plan

METAS = {
    "holdings": DatasetMeta(columns={"sector", "region", "weight"}, metrics={"Total weight", "Positions"}),
}

METAS_H = {
    "holdings": DatasetMeta(columns={"sector", "as_of_date"}, metrics={"Positions"}),
}


def _chart(**kw) -> ChartSpec:
    base = dict(title="C1", viz_type="table", dataset="holdings", metrics=["Positions"], groupby=["sector"])
    return ChartSpec(**{**base, **kw})


def _plan(*charts: ChartSpec) -> ChartPlan:
    return ChartPlan(title="P", charts=list(charts))


def test_valid_plan_has_no_errors():
    assert validate_plan(_plan(_chart()), METAS) == []


def test_unknown_dataset_rejected():
    errs = validate_plan(_plan(_chart(dataset="secret_table")), METAS)
    assert len(errs) == 1 and "secret_table" in errs[0] and "C1" in errs[0]


def test_unknown_metric_rejected_names_chart_title():
    errs = validate_plan(_plan(_chart(title="Weights", metrics=["Nope"])), METAS)
    assert len(errs) == 1 and "Weights" in errs[0] and "Nope" in errs[0]


def test_unknown_groupby_column_rejected():
    errs = validate_plan(_plan(_chart(groupby=["bogus"])), METAS)
    assert len(errs) == 1 and "bogus" in errs[0]


def test_filter_column_must_exist():
    errs = validate_plan(_plan(_chart(filters={"bogus": "x"})), METAS)
    assert len(errs) == 1 and "bogus" in errs[0]


def test_viz_type_outside_allowlist_rejected():
    errs = validate_plan(_plan(_chart(viz_type="sankey")), METAS)
    assert len(errs) == 1 and "sankey" in errs[0]


def test_more_than_max_charts_rejected():
    charts = [_chart(title=f"C{i}") for i in range(MAX_CHARTS + 1)]
    errs = validate_plan(_plan(*charts), METAS)
    assert len(errs) == 1 and str(MAX_CHARTS) in errs[0]


def test_empty_plan_rejected():
    assert len(validate_plan(_plan(), METAS)) == 1


def test_empty_metrics_rejected():
    errs = validate_plan(_plan(_chart(metrics=[])), METAS)
    assert len(errs) == 1 and "C1" in errs[0]


def test_pivot_requires_two_groupby():
    one = validate_plan(_plan(_chart(viz_type="pivot_table_v2", groupby=["sector"])), METAS)
    assert len(one) == 1 and "pivot_table_v2" in one[0]
    two = validate_plan(_plan(_chart(viz_type="pivot_table_v2", groupby=["sector", "region"])), METAS)
    assert two == []


def test_duplicate_title_rejected():
    errs = validate_plan(_plan(_chart(), _chart()), METAS)
    assert len(errs) == 1 and "C1" in errs[0] and "duplicate" in errs[0].lower()


def test_line_first_groupby_must_be_temporal():
    ok = validate_plan(_plan(_chart(viz_type="echarts_timeseries_line", groupby=["as_of_date"])), METAS_H)
    assert ok == []
    errs = validate_plan(_plan(_chart(viz_type="echarts_timeseries_line", groupby=["sector"])), METAS_H)
    assert len(errs) == 1 and "C1" in errs[0] and "'sector'" in errs[0]


@pytest.mark.parametrize(
    "viz,n",
    [
        ("echarts_timeseries_bar", 1),
        ("echarts_timeseries_line", 1),
        ("treemap_v2", 1),
        ("pie", 1),
        ("heatmap_v2", 2),
        ("pivot_table_v2", 2),
    ],
)
def test_min_groupby_per_viz(viz, n):
    errs = validate_plan(_plan(_chart(viz_type=viz, groupby=[])), METAS_H)
    assert any("C1" in e and viz in e and f"at least {n}" in e for e in errs)


def test_big_number_rejects_groupby():
    errs = validate_plan(_plan(_chart(viz_type="big_number_total", groupby=["sector"])), METAS_H)
    assert len(errs) == 1 and "big_number_total" in errs[0] and "sector" in errs[0]
    assert validate_plan(_plan(_chart(viz_type="big_number_total", groupby=[])), METAS_H) == []


def test_heatmap_rejects_a_third_groupby():
    errs = validate_plan(_plan(_chart(viz_type="heatmap_v2", groupby=["sector", "as_of_date", "sector"])), METAS_H)
    assert len(errs) == 1 and "heatmap_v2" in errs[0] and "at most 2" in errs[0]


@pytest.mark.parametrize("viz,groupby", [("big_number_total", []), ("pie", ["sector"]), ("treemap_v2", ["sector"])])
def test_single_metric_viz_rejects_a_second_metric(viz, groupby):
    two = dict(metrics=["Total weight", "Positions"])
    errs = validate_plan(_plan(_chart(viz_type=viz, groupby=groupby, **two)), METAS)
    assert len(errs) == 1 and viz in errs[0] and "exactly one metric" in errs[0]
    assert validate_plan(_plan(_chart(viz_type=viz, groupby=groupby)), METAS) == []


def test_heatmap_rejects_a_second_metric():
    errs = validate_plan(
        _plan(_chart(viz_type="heatmap_v2", groupby=["sector", "region"], metrics=["Total weight", "Positions"])), METAS
    )
    assert len(errs) == 1 and "exactly one metric" in errs[0]


METAS_HH = {"holdings_history": DatasetMeta(columns={"sector", "as_of_date", "portfolio_name"}, metrics={"Positions"})}


def test_holdings_history_needs_as_of_date_first():
    # summing across snapshots double-counts, so history is for charts over time only
    bar = _chart(title="Sectors", viz_type="echarts_timeseries_bar", dataset="holdings_history", groupby=["sector"])
    (err,) = validate_plan(_plan(bar), METAS_HH)
    assert "Chart 'Sectors'" in err and "as_of_date" in err and "double-count" in err
    big = _chart(title="Total", viz_type="big_number_total", dataset="holdings_history", groupby=[])
    assert len(validate_plan(_plan(big), METAS_HH)) == 1
    line = _chart(viz_type="echarts_timeseries_line", dataset="holdings_history", groupby=["as_of_date", "portfolio_name"])
    assert validate_plan(_plan(line), METAS_HH) == []


def test_filter_on_project_id_is_accepted_for_holdings_datasets():
    from arp.bi.catalog import VIEW_DATASETS

    for name, ds in VIEW_DATASETS.items():
        if name.startswith("holdings"):
            metas = {name: DatasetMeta(columns=set(ds.columns), metrics={"Holdings"})}
            chart = _chart(dataset=name, metrics=["Holdings"], groupby=["as_of_date"], filters={"project_id": "alpha"})
            assert validate_plan(_plan(chart), metas) == []
