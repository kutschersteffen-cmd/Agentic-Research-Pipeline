"""Compile a ChartPlan into Superset chart `params` and dashboard `position_json`.

Pure: no network, no randomness. Output shapes mirror the params recorded in
tests/fixtures/bi/ (accepted and rendered by Superset 5.0.0 in the Task 4 live
test); `SupersetClient.create_chart` adds `datasource` and `viz_type`.
"""

from __future__ import annotations

import hashlib
import json

from arp.bi.catalog import MIN_GROUPBY
from arp.bi.plan import ChartPlan, ChartSpec, NativeFilter

_FMT = "SMART_NUMBER"


def _adhoc(filters: dict[str, str]) -> list[dict]:
    # SIMPLE only: SupersetClient._query drops SQL-type adhoc filters.
    return [
        {"expressionType": "SIMPLE", "subject": c, "operator": "==", "comparator": v, "clause": "WHERE"}
        for c, v in filters.items()
    ]


def _per_viz(viz: str, metrics: list[str], g: list[str]) -> dict:
    """Viz-specific controls. `groupby` is ordered: for axis-based charts the
    first column is the x axis (heatmap: second is the y axis; pivot: first is
    the rows, the rest the columns)."""
    if viz == "big_number_total":
        return {
            "metric": metrics[0],
            "header_font_size": 0.4,
            "subheader_font_size": 0.15,
            "y_axis_format": _FMT,
            "time_format": "smart_date",
        }
    if viz == "echarts_timeseries_bar":
        return {
            "x_axis": g[0],
            "metrics": metrics,
            "groupby": g[1:],
            "row_limit": 10000,
            "order_desc": True,
            "x_axis_sort_asc": True,
            "orientation": "vertical",
            "show_legend": True,
            "y_axis_format": _FMT,
        }
    if viz == "echarts_timeseries_line":
        # ponytail: x axis assumed temporal (month grain); a non-date first column needs a grain-less variant
        return {
            "x_axis": g[0],
            "time_grain_sqla": "P1M",
            "metrics": metrics,
            "groupby": g[1:],
            "row_limit": 10000,
            "order_desc": True,
            "show_legend": True,
            "y_axis_format": _FMT,
            "x_axis_time_format": "smart_date",
        }
    if viz == "heatmap_v2":
        return {
            "x_axis": g[0],
            "groupby": g[1:2],
            "metric": metrics[0],
            "row_limit": 10000,
            "normalize_across": "heatmap",
            "sort_x_axis": "alpha_asc",
            "sort_y_axis": "alpha_asc",
            "linear_color_scheme": "blue_white_yellow",
            "show_legend": True,
            "show_percentage": True,
            "y_axis_format": _FMT,
        }
    if viz == "pie":
        return {
            "groupby": g,
            "metric": metrics[0],
            "row_limit": 100,
            "sort_by_metric": True,
            "show_legend": True,
            "show_labels": True,
            "label_type": "key",
            "number_format": _FMT,
        }
    if viz == "pivot_table_v2":
        return {
            "groupbyRows": g[:1],
            "groupbyColumns": g[1:],
            "metrics": metrics,
            "metricsLayout": "COLUMNS",
            "aggregateFunction": "Sum",
            "row_limit": 10000,
            "order_desc": True,
            "valueFormat": _FMT,
            "date_format": "smart_date",
            "rowOrder": "key_a_to_z",
            "colOrder": "key_a_to_z",
        }
    if viz == "table":
        return {
            "query_mode": "aggregate",
            "groupby": g,
            "metrics": metrics,
            "all_columns": [],
            "percent_metrics": [],
            "order_desc": True,
            "row_limit": 1000,
            "table_timestamp_format": "smart_date",
        }
    if viz == "treemap_v2":
        return {
            "groupby": g,
            "metric": metrics[0],
            "row_limit": 10000,
            "show_labels": True,
            "label_type": "key_value",
            "number_format": _FMT,
        }
    raise ValueError(f"unsupported viz_type {viz!r}")


def compile_chart(spec: ChartSpec, dataset_id: int) -> dict:
    # dataset_id is unused: the client adds the datasource; kept for the agreed signature.
    if not spec.metrics:
        raise ValueError(f"{spec.viz_type} needs at least one metric")
    if len(spec.groupby) < MIN_GROUPBY.get(spec.viz_type, 0):
        raise ValueError(f"{spec.viz_type} needs at least {MIN_GROUPBY[spec.viz_type]} groupby column(s)")
    params = _per_viz(spec.viz_type, spec.metrics, spec.groupby)
    params["adhoc_filters"] = _adhoc(spec.filters)
    return params


def compile_dashboard(chart_ids: list[int], titles: list[str]) -> dict:
    """Two charts per row. Not verified against live Superset by this task's tests."""
    pos = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
    }
    for i in range(0, len(chart_ids), 2):
        row = f"ROW-{i // 2}"
        pos["GRID_ID"]["children"].append(row)
        pos[row] = {
            "type": "ROW",
            "id": row,
            "children": [],
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        for cid, title in zip(chart_ids[i : i + 2], titles[i : i + 2], strict=True):
            key = f"CHART-{cid}"
            pos[row]["children"].append(key)
            pos[key] = {
                "type": "CHART",
                "id": key,
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row],
                "meta": {"chartId": cid, "width": 6, "height": 50, "sliceName": title},
            }
    return pos


def compile_native_filters(filters: list[NativeFilter], dataset_ids: dict[str, int]) -> dict:
    """Superset `json_metadata` holding one select filter per NativeFilter,
    scoped to the whole dashboard. Ids are derived from dataset+column, so a
    rebuild keeps them (and any saved filter state / URLs) stable.

    Verified on Superset 5.0.0: one filter targeting `holdings.portfolio_name`
    also filters charts on `holdings_history`. The filter's value is applied
    to every chart in scope by column name; the target dataset only feeds the
    value list. So one filter per column is enough while the datasets share
    the column name. The ROOT_ID scope covers every chart, so no chart ids are needed.
    """
    out = []
    for f in filters:
        if f.dataset not in dataset_ids:
            raise ValueError(f"native filter {f.name!r}: dataset {f.dataset!r} not in dataset_ids")
        fid = f"NATIVE_FILTER-{f.dataset}-{f.column}"
        if any(o["id"] == fid for o in out):
            raise ValueError(f"duplicate native filter on {f.dataset}.{f.column}")
        item = {
                "id": fid,
                "name": f.name,
                "filterType": "filter_select",
                "type": "NATIVE_FILTER",
                "targets": [{"datasetId": dataset_ids[f.dataset], "column": {"name": f.column}}],
                "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
                "controlValues": {
                    "enableEmptyFilter": False,
                    "defaultToFirstItem": False,
                    "multiSelect": True,
                    "searchAllOptions": False,
                    "inverseSelection": False,
                },
                "defaultDataMask": {"extraFormData": {}, "filterState": {}},
                "cascadeParentIds": [],
                "description": "",
        }
        if f.filters:
            item["adhoc_filters"] = _adhoc(f.filters)  # "Pre-filter available values"
        out.append(item)
    return {"native_filter_configuration": out}


def plan_hash(plan: ChartPlan) -> str:
    # sort_keys makes filter dict order irrelevant; the charts list stays positional.
    canonical = json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]
